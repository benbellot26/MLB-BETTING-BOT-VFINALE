from __future__ import annotations

from . import v138_audit_closure
from . import v138_dataset_store
from . import v138_monitoring
from . import v138_research_models
from . import v138_validation_entry


def main() -> None:
    v138_research_models.main()
    v138_validation_entry.main()
    v138_dataset_store.main()
    v138_monitoring.main()
    v138_audit_closure.main()


if __name__=="__main__":main()
