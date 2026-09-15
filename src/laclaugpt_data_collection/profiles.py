"""Composable Collection deployment profiles; no services are contacted here."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
@dataclass(frozen=True)
class DeploymentProfile:
    machine: str='laptop'; execution: str='cli'; storage: str='local'; browser: str='firefox-local'; runtime_root: Path=Path('data')
    def validate(self)->None:
        if self.machine not in {'laptop','linux-server','custom'}: raise ValueError('unknown machine')
        if self.execution not in {'cli','cron','systemd','agent'}: raise ValueError('unknown execution')
        if self.storage not in {'local','distributed','custom'}: raise ValueError('unknown storage')
        if self.browser not in {'firefox-local','headless-worker','none','custom'}: raise ValueError('unknown browser')
        if self.browser=='firefox-local' and self.machine!='laptop': raise ValueError('firefox-local is a laptop profile')
def laptop(root: str|Path='data')->DeploymentProfile: return DeploymentProfile(runtime_root=Path(root))
def linux_server(root: str|Path='data',storage: str='local')->DeploymentProfile: return DeploymentProfile(machine='linux-server',execution='cron',storage=storage,browser='none',runtime_root=Path(root))
