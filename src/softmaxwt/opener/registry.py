from softmaxwt.opener.cmux import CmuxOpener
from softmaxwt.opener.common import Opener, OpenerName
from softmaxwt.opener.inplace import InplaceOpener
from softmaxwt.opener.noop import NoopOpener
from softmaxwt.opener.zellij import ZellijOpener

_OPENERS: dict[OpenerName, type[Opener]] = {
    OpenerName.inplace: InplaceOpener,
    OpenerName.cmux: CmuxOpener,
    OpenerName.zellij: ZellijOpener,
    OpenerName.noop: NoopOpener,
}


def get_opener(name: OpenerName) -> Opener:
    return _OPENERS[name]()


def all_openers() -> list[Opener]:
    return [cls() for cls in _OPENERS.values()]
