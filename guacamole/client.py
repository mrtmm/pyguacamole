"""
The underlying work for this code is published under the MIT License (MIT)
(https://pypi.org/project/pyguacamole/)
"""

import socket
import logging

from .exceptions import GuacamoleError

from .instruction import INST_TERM
from .instruction import GuacamoleInstruction as Instruction

# supported protocols
PROTOCOLS = ('vnc', 'rdp', 'ssh')

# maximum amount of data to be received from the socket at once, in bytes
BUFFER_LENGTH = 4096



class GuacamoleClient(object):
    """Guacamole Client class."""

    def __init__(self,
                 host,
                 port,
                 timeout=20,
                 loglevel=logging.DEBUG,
                 logger=guac_logger):
        """
        Guacamole Client class. This class can handle communication with guacd
        server.

        :param host: guacd server host.

        :param port: guacd server port.

        :param timeout: socket connection timeout.

        :param loglevel: logging level, defaults to Debug level.

        :param logger: logger for GuacamoleCLient class.
        """
        self.host = host
        self.port = port
        self.timeout = timeout

        self._client = None

        # handshake established?
        self.connected = False

        # Receiving buffer
        self._buffer = bytearray()

        # Client ID
        self._id = None

        self.logger = logger

    @property
    def client(self):
        """
        Socket connection.
        """
        if not self._client:
            self._client = socket.create_connection(
                (self.host, self.port), self.timeout)
            self.logger.info('Client connected with guacd server (%s, %s, %s)'
                             % (self.host, self.port, self.timeout))

        return self._client

    @property
    def id(self):
        """Return client id"""
        return self._id

    def close(self):
        """
        Terminate connection with Guacamole guacd server.
        """
        self.client.close()
        self._client = None
        self.connected = False
        self.logger.info('Connection closed.')

    def receive(self):
        """
        Receive instructions from Guacamole guacd server.
        """
        start = 0

        while True:
            idx = self._buffer.find(INST_TERM.encode('utf-8'), start)
            if idx != -1:
                # instruction was fully received!
                line = self._buffer[:idx + 1]
                self._buffer = self._buffer[idx + 1:]
                self.logger.debug('Received instruction: %s' % line)
                return line
            else:
                start = len(self._buffer)
                # we are still waiting for instruction termination
                buf = self.client.recv(BUFFER_LENGTH)
                if not buf:
                    # No data received, connection lost?!
                    self.close()
                    self.logger.warn(
                        'Failed to receive instruction. Closing.')
                    return None
                self._buffer.extend(buf)

    def send(self, data):
        """
        Send encoded instructions to Guacamole guacd server.
        """
        self.logger.debug('Sending data: %s' % data)

        if isinstance(data, str):
            data = data.encode('utf-8')
        self.client.sendall(data)

    def read_instruction(self):
        """
        Read and decode instruction.
        """
        self.logger.debug('Reading instruction.')
        return Instruction.load(self.receive())

    def send_instruction(self, instruction):
        """
        Send instruction after encoding.
        """
        self.logger.debug('Sending instruction: %s' % str(instruction))
        return self.send(instruction.encode())

    def handshake(self, protocol='ssh', width=1024, height=768, dpi=96,
                  audio=None, video=None, image=None, **kwargs):
        """
        Establish connection with Guacamole guacd server via handshake.
        """
        if protocol not in PROTOCOLS and 'connectionid' not in kwargs:
            self.logger.error(
                'Invalid protocol: %s and no connectionid provided' % protocol)
            raise GuacamoleError(
                'Cannot start Handshake. Missing protocol or connectionid.')

        if audio is None:
            audio = list()

        if video is None:
            video = list()

        if image is None:
            image = list()

        # 1. Send 'select' instruction
        self.logger.debug('Send `select` instruction.')

        # if connectionid is provided - connect to existing connectionid
        if 'connectionid' in kwargs:
            self.send_instruction(Instruction('select',
                                              kwargs.get('connectionid')))
        else:
            self.send_instruction(Instruction('select', protocol))

        # 2. Receive `args` instruction
        instruction = self.read_instruction()
        self.logger.debug('Expecting `args` instruction, received: %s'
                          % str(instruction))

        if not instruction:
            self.close()
            raise GuacamoleError(
                'Cannot establish Handshake. Connection Lost!')

        if instruction.opcode != 'args':
            self.close()
            raise GuacamoleError(
                'Cannot establish Handshake. Expected opcode `args`, '
                'received `%s` instead.' % instruction.opcode)

        # 3. Respond with size, audio & video support
        self.logger.debug('Send `size` instruction (%s, %s, %s)'
                          % (width, height, dpi))
        self.send_instruction(Instruction('size', width, height, dpi))

        self.logger.debug('Send `audio` instruction (%s)' % audio)
        self.send_instruction(Instruction('audio', *audio))

        self.logger.debug('Send `video` instruction (%s)' % video)
        self.send_instruction(Instruction('video', *video))

        self.logger.debug('Send `image` instruction (%s)' % image)
        self.send_instruction(Instruction('image', *image))

        # 4. Send `connect` instruction with proper values
        connection_args = [
            kwargs.get(arg.replace('-', '_'), '') for arg in instruction.args
        ]

        self.logger.debug('Send `connect` instruction (%s)' % connection_args)
        self.send_instruction(Instruction('connect', *connection_args))

        # 5. Receive ``ready`` instruction, with client ID.
        instruction = self.read_instruction()
        self.logger.debug('Expecting `ready` instruction, received: %s'
                          % str(instruction))

        if instruction.opcode != 'ready':
            self.logger.warning(
                'Expected `ready` instruction, received: %s instead')

        if instruction.args:
            self._id = instruction.args[0]
            self.logger.debug(
                'Established connection with client id: %s' % self.id)

        self.logger.debug('Handshake completed.')
        self.connected = True
