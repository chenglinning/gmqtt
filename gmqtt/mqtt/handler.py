import asyncio
import logging
import struct
import time

from .constants import MQTTCommands


logger = logging.getLogger(__name__)


def _empty_callback(*args, **kwargs):
    pass


class EventCallback(object):
    def __init__(self, *args, **kwargs):
        super(EventCallback, self).__init__(*args, **kwargs)

        self._connected = asyncio.Event()

        self._on_connected_callback = _empty_callback
        self._on_disconnected_callback = _empty_callback
        self._on_message_callback = _empty_callback
        self._on_subscribe_callback = _empty_callback

    @property
    def on_subscribe(self):
        return self._on_subscribe_callback

    @on_subscribe.setter
    def on_subscribe(self, cb):
        if not callable(cb):
            raise ValueError
        self._on_subscribe_callback = cb

    @property
    def on_connect(self):
        return self._on_connected_callback

    @on_connect.setter
    def on_connect(self, cb):
        if not callable(cb):
            raise ValueError
        self._on_connected_callback = cb

    @property
    def on_message(self):
        return self._on_message_callback

    @on_message.setter
    def on_message(self, cb):
        if not callable(cb):
            raise ValueError
        self._on_message_callback = cb

    @property
    def on_disconnect(self):
        return self._on_disconnected_callback

    @on_disconnect.setter
    def on_disconnect(self, cb):
        if not callable(cb):
            raise ValueError
        self._on_disconnected_callback = cb


class MqttPackageHandler(EventCallback):
    def __init__(self, *args, **kwargs):
        super(MqttPackageHandler, self).__init__(*args, **kwargs)
        self._messages_in = {}

    def _send_command_with_mid(self, cmd, mid, dup):
        raise NotImplementedError

    def _send_puback(self, mid):
        self._send_command_with_mid(MQTTCommands.PUBACK, mid, False)

    def _send_pubrec(self, mid):
        self._send_command_with_mid(MQTTCommands.PUBREC, mid, False)

    def _send_pubrel(self, mid, dup):
        self._send_command_with_mid(MQTTCommands.PUBREL | 2, mid, dup)

    def _handle_packet(self, cmd, packet):
        logger.debug('[CMD %s] %s', hex(cmd), packet)
        handler_name = '_handle_{}_packet'.format(MQTTCommands(cmd).name.lower())

        handler = getattr(self, handler_name, self._default_handler)

        handler(cmd, packet)
        self._last_msg_in = time.monotonic()

    def _default_handler(self, cmd, packet):
        logger.warning('[UNKNOWN CMD] %s %s', hex(cmd), packet)

    def _handle_disconnect_packet(self, cmd, packet):
        self.on_disconnect(self, packet)

    def _handle_connack_packet(self, cmd, packet):
        self._connected.set()
        if len(packet) != 2:
            raise ValueError()

        (flags, result) = struct.unpack("!BB", packet)

        # TODO: Implement checking for the flags and results
        # see 3.2.2.3 Connect Return code of the http://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.pdf

        logger.debug('[CONNACK] flags: %s, result: %s', hex(flags), hex(result))
        self.on_connect(self, flags, result)

    def _handle_publish_packet(self, cmd, raw_packet):
        header = cmd

        dup = (header & 0x08) >> 3
        qos = (header & 0x06) >> 1
        retain = header & 0x01

        pack_format = "!H" + str(len(raw_packet) - 2) + 's'
        (slen, packet) = struct.unpack(pack_format, raw_packet)

        pack_format = '!' + str(slen) + 's' + str(len(packet) - slen) + 's'
        (topic, packet) = struct.unpack(pack_format, packet)

        if len(topic) == 0:
            logger.warning('[MQTT ERR PROTO] topic name is empty')
            return

        print_topic = topic.decode('utf-8')
        payload = packet

        logger.debug('[RECV %s with QoS: %s] %s', print_topic, qos, payload)

        # TODO: send confirmation msg
        if qos > 0:
            pack_format = "!H" + str(len(packet) - 2) + 's'
            (mid, packet) = struct.unpack(pack_format, packet)
        else:
            mid = None

        if qos == 0:
            self.on_message(self, print_topic, payload, qos)
        elif qos == 1:
            self._send_puback(mid)
            self.on_message(self, print_topic, payload, qos)
        elif qos == 2:
            self._send_pubrec(mid)
            self.on_message(self, print_topic, payload, qos)

    def __call__(self, cmd, packet):
        try:
            result = self._handle_packet(cmd, packet)
        except Exception as exc:
            logger.error('[ERROR HANDLE PKG]', exc_info=exc)
            result = None
        return result

    def _handle_suback_packet(self, cmd, raw_packet):
        pack_format = "!H" + str(len(raw_packet) - 2) + 's'
        (mid, packet) = struct.unpack(pack_format, raw_packet)
        pack_format = "!" + "B" * len(packet)
        granted_qos = struct.unpack(pack_format, packet)

        logger.info('[SUBACK] %s %s', mid, granted_qos)
        self.on_subscribe(self, mid, granted_qos)

    def _handle_pingreq_packet(self, cmd, packet):
        logger.info('[PING REQUEST] %s %s', hex(cmd), packet)
        pass

    def _handle_pingresp_packet(self, cmd, packet):
        logger.info('[PONG REQUEST] %s %s', hex(cmd), packet)

    def _handle_puback_packet(self, cmd, packet):
        pass

    def _handle_pubcomp_packet(self, cmd, packet):
        pass

    def _handle_pubrec_packet(self, cmd, packet):
        pass

    def _handle_pubrel_packet(self, cmd, packet):
        mid, = struct.unpack("!H", packet)

        if mid not in self._messages_in:
            return

        topic, payload, qos = self._messages_in[mid]




