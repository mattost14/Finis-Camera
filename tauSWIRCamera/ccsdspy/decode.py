from os.path import (dirname, basename, abspath, join)

import importlib.util
import sys

file_name = basename(__file__)
module_name = __name__.split('.')[0]
script_path = dirname(abspath(__file__))
file_path = join(script_path, *['..', f'{module_name}-git', module_name, file_name])
module_name = f'{__name__}-internal'
this_module = sys.modules[__name__]

spec = importlib.util.spec_from_file_location(module_name, file_path)
module = importlib.util.module_from_spec(spec)
sys.modules[module_name] = module
spec.loader.exec_module(module)
for attr in module.__dict__:
    #if attr[0] == '_': continue
    setattr(this_module, attr, getattr(module, attr))
