import sys
import functools
import traceback
import os

try:
    import xbmc
    from . import addon
except ImportError:
    import logging
    xbmc_log = False
else:
    xbmc_log = True


if xbmc_log:
    def _log(txt, level=xbmc.LOGDEBUG):
        if not (addon.get_setting('debug') == 'false' and level == xbmc.LOGDEBUG):
            msg = '{}: {}'.format(addon.name, txt)
            xbmc.log(msg, level)
            
    def log(txt):
        _log(txt, level=xbmc.LOGDEBUG)
    
    def log_error(txt):
        _log(txt, level=xbmc.LOGERROR)
else:
    log_path = os.path.join(os.path.expanduser('~'), 'devupdate.log')
    logging.basicConfig(filename=log_path,
                        level=logging.ERROR,
                        format='%(asctime)s %(levelname)7s: %(message)s')

    def log(txt):
        logging.debug(txt)
        
    def log_error(txt):
        logging.error(txt)


def log_exception():
    log_error("".join(traceback.format_exception(*sys.exc_info())))


def with_logging(msg_success=None, msg_error=None, log_exc=True):
    def wrap(func):
        @functools.wraps(func)
        def call_with_logging(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
            except:
                if msg_error is not None:
                    log_error(msg_error.format(*args))
                if log_exc:
                    log_exception()
            else:
                if msg_success is not None:
                    log(msg_success.format(*args))
                return result
        return call_with_logging
    return wrap


def log_version():
    log("version {}".format(addon.version))
