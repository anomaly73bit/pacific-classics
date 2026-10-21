from .autoscout24 import AutoScout24
from .kleinanzeigen import Kleinanzeigen
from .mobilede import MobileDe
from .sauto import Sauto
from .willhaben import Willhaben

REGISTRY = {cls.key: cls for cls in (AutoScout24, Sauto, Willhaben, Kleinanzeigen, MobileDe)}
