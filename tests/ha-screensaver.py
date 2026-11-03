"""Run in a Home Assistant image, with fake services and no network or real TVs."""
import asyncio
import copy
import json
import logging
from pathlib import Path
import sys
import tempfile
import yaml
from homeassistant.core import HomeAssistant, Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.script import Script
from homeassistant.const import __version__

class Input:
    def __init__(self, name): self.name = name
class Loader(yaml.SafeLoader): pass
Loader.add_constructor('!input', lambda loader, node: Input(loader.construct_scalar(node)))
blueprint = yaml.load(Path(sys.argv[1]).read_text(), Loader=Loader)
inputs = {name: row['default'] for name, row in blueprint['blueprint']['input'].items() if 'default' in row}
inputs.update(tv='media_player.fixture', stream='ws://127.0.0.1/fixture', dismiss_screensaver=True)
def expand(value):
    if isinstance(value, Input): return inputs[value.name]
    if isinstance(value, dict): return {k: expand(v) for k, v in value.items()}
    if isinstance(value, list): return [expand(v) for v in value]
    return value
sequence = expand(blueprint['sequence'])
assert sequence[1]['then'][0]['continue_on_error'] is True
assert 'continue_on_error' not in sequence[-1]

async def main():
    checks = []
    with tempfile.TemporaryDirectory(prefix='overlay-regression-') as folder:
        hass = HomeAssistant(folder)
        for name, rejection, enabled, initial, after, launch_error, old in [
            ('baseline reproduces issue 28', True, True, 'on', 'on', False, True),
            ('already-on rejection still launches', True, True, 'on', 'on', False, False),
            ('successful dismissal launches', False, True, 'on', 'on', False, False),
            ('disabled option skips screen-on', True, False, 'on', 'on', False, False),
            ('off TV is not touched', True, True, 'off', 'off', False, False),
            ('unavailable TV is not touched', True, True, 'unavailable', 'unavailable', False, False),
            ('off after screen-on blocks launch', True, True, 'on', 'off', False, False),
            ('unavailable after screen-on blocks launch', False, True, 'on', 'unavailable', False, False),
            ('launch error remains a failure', True, True, 'on', 'on', True, False),
        ]:
            calls = []
            async def command(call):
                cmd = call.data['command']; calls.append(cmd)
                if cmd.endswith('/turnOnScreen'):
                    hass.states.async_set('media_player.fixture', after)
                    if rejection: raise HomeAssistantError("500 Application error: The current state must be 'Screen Off'")
                elif launch_error: raise HomeAssistantError('Launch rejected')
            hass.services.async_register('webostv', 'command', command)
            hass.states.async_set('media_player.fixture', initial)
            steps = copy.deepcopy(sequence)
            if old: del steps[1]['then'][0]['continue_on_error']
            runner = Script(hass, cv.SCRIPT_SCHEMA(steps), name, 'script')
            failed = False
            try: await runner.async_run({'restore_screen': enabled}, Context())
            except HomeAssistantError: failed = True
            expected = [] if initial != 'on' else ([] if not enabled else ['com.webos.service.tvpower/power/turnOnScreen'])
            if initial == 'on' and (not enabled or (after == 'on' and not old)): expected += ['system.launcher/launch']
            assert calls == expected, (name, calls, expected)
            assert failed == (old or launch_error), (name, failed)
            checks.append(name)
        await hass.async_stop()
    print(json.dumps({'passed': True, 'ha_version': __version__, 'checks': checks}))

logging.disable(logging.CRITICAL)
asyncio.run(main())
