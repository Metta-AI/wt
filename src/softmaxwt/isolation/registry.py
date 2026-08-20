from softmaxwt.isolation.common import IsolationBackend, IsolationMode
from softmaxwt.isolation.nono import NonoBackend
from softmaxwt.isolation.raw import RawBackend

_BACKENDS: dict[IsolationMode, type[IsolationBackend]] = {
    IsolationMode.raw: RawBackend,
    IsolationMode.nono: NonoBackend,
}


def get_isolation_backend(mode: IsolationMode) -> IsolationBackend:
    return _BACKENDS[mode]()


def all_isolation_backends() -> list[IsolationBackend]:
    return [cls() for cls in _BACKENDS.values()]
