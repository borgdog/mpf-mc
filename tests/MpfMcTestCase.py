import unittest
import sys

from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.config import Config

from mc.core.utils import load_machine_config
from mpf.system.config import Config as MpfConfig
from mpf.system.utility_functions import Util
from kivy.logger import FileHandler
from kivy.graphics import Fbo

Config.set('kivy', 'log_enable', '0')
Config.set('kivy', 'log_level', 'warning')

from mc.core.mc import MpfMc
from time import time, sleep


class TestMpfMc(MpfMc):
    def __init__(self, options, config, machine_path, **kwargs):
        super().__init__(options, config, machine_path, **kwargs)
        sys.path.append(self.machine_path)

        # Sometiems the purging takes too long and the next test fails because
        # it can't open the log file, so disable purging for tests.
        FileHandler.purge_logs = self.null_purge

    def null_purge(self, *args, **kwargs):
        pass


class MpfMcTestCase(unittest.TestCase):
    def __init__(self, *args):
        self.sent_bcp_commands = list()
        super().__init__(*args)

    def get_options(self):

        return dict(machine_path=self.get_machine_path(),
                    mcconfigfile='mc/mcconfig.yaml',
                    configfile=Util.string_to_list(self.get_config_file()),
                    bcp=False)

    def get_machine_path(self):
        raise NotImplementedError

    def get_config_file(self):
        raise NotImplementedError

    def preprocess_config(self, config):
        # TODO this method is copied from the mc.py launcher. Prob a better way
        kivy_config = config['kivy_config']

        try:
            kivy_config['graphics'].update(config['displays']['window'])
        except KeyError:
            pass

        try:
            kivy_config['graphics'].update(config['window'])
        except KeyError:
            pass

        if 'top' in kivy_config['graphics'] and 'left' in kivy_config[
            'graphics']:
            kivy_config['graphics']['position'] = 'custom'

        for section, settings in kivy_config.items():
            for k, v in settings.items():
                try:
                    if k in Config[section]:
                        Config.set(section, k, v)
                except KeyError:
                    continue

    def advance_time(self, secs=.1):
        start = time()
        self.mc.events._process_event_queue()
        while time() < start + secs:
            sleep(.01)
            self.mc.events._process_event_queue()
            EventLoop.idle()

    def get_pixel_color(self, x, y):
        # do the imports here because we don't want to import Window at the
        # top or else we won't be able to set window properties
        # from kivy.core.window import Window
        from kivy.graphics.opengl import glReadPixels, GL_RGB, GL_UNSIGNED_BYTE
        return glReadPixels(x, y, 1, 1, GL_RGB, GL_UNSIGNED_BYTE)

    def setUp(self):
        # Most of the setup is done in run(). Explanation is there.
        Config._named_configs.pop('app', None)

    def tearDown(self):
        from kivy.base import stopTouchApp
        from kivy.core.window import Window
        Window.unbind(on_flip=self.on_window_flip)
        stopTouchApp()

    def patch_bcp(self):
        # used internally
        self.orig_bcp_send = self.mc.bcp_processor.send
        self.mc.bcp_processor.send = self._bcp_send

        # this is used to send BCP commands to mpf_mc
        self.send = self.mc.bcp_processor._process_command

    def _bcp_send(self, bcp_command, callback=None, **kwargs):
        # used for commands sent from the MC to the PC
        # print((bcp_command, callback, kwargs))
        self.sent_bcp_commands.append((bcp_command, callback, kwargs))
        self.orig_bcp_send(bcp_command=bcp_command, callback=callback,
                           **kwargs)

    def run(self, name):
        print("Running", self.id())
        # This setup is done in run() because we need to give control to the
        # kivy event loop which we can only do by returning from the run()
        # that's called. So we override run() and setup mpf_mc and then call
        # our own run_test() on a callback. Then we can wait until the
        # environment is setup (which can take a few frames), then we call
        # super().run() to get the actual TestCase.run() method to run and
        # we return the results.

        # We have to do this in run() and not setUp() because run actually
        # calls setUp(), so since we were overriding it ours doesn't call it
        # so we just do our setup here since if we manually called setUp() then
        # it would be called again when we call super().run().
        self._test_name = name

        mpf_config = MpfConfig.load_config_file(self.get_options()[
                                                    'mcconfigfile'])

        mpf_config = load_machine_config(
                Util.string_to_list(self.get_config_file()),
                self.get_machine_path(),
                mpf_config['mpf_mc']['paths']['config'], mpf_config)
        self.preprocess_config(mpf_config)

        self.mc = TestMpfMc(options=self.get_options(),
                            config=mpf_config,
                            machine_path=self.get_machine_path())

        self.patch_bcp()

        from kivy.core.window import Window
        Window.bind(on_flip=self.on_window_flip)
        Window.create_window()
        Window.canvas.clear()

        Clock.schedule_once(self.run_test, 0)
        self.mc.run()

    def run_test(self, time):
        # set the title bar, just for fun. :)
        self.mc.title = str(self._test_name)

        if not self.mc.init_done:
            Clock.schedule_once(self.run_test, 0)
            return

        return super().run(self._test_name)
