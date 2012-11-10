import re

CURRENT_BUILD = int(re.search('-r(\d+)', open('/etc/version').read()).group(1))
ARCH = open('/etc/arch').read().rstrip()

HEADERS={'User-agent' : "Mozilla/5.0"}