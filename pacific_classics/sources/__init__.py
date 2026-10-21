from .autobazar import Autobazar
from .autoscout24 import AutoScout24
from .classictrader import ClassicTrader
from .kleinanzeigen import Kleinanzeigen
from .marktplaats import Marktplaats, Tweedehands
from .mobilede import MobileDe
from .sauto import Sauto
from .willhaben import Willhaben

REGISTRY = {cls.key: cls for cls in (AutoScout24, Sauto, Willhaben, Kleinanzeigen, MobileDe,
                                     Autobazar, Marktplaats, Tweedehands, ClassicTrader)}
