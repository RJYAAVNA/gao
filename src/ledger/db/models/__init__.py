"""ORM 模型集中导出。

Alembic 的 env.py 依赖这里把全部模型注册到 Base.metadata，
因此新增模型文件后必须在此导入，否则自动生成迁移会漏表。
"""

from ledger.db.base import Base
from ledger.db.models.catalog import (
    DataSource,
    Institution,
    InstitutionType,
    Product,
    ProductDistribution,
    ProductSourceMapping,
    ValuationMethod,
)
from ledger.db.models.identity import (
    AuditEvent,
    AuthSession,
    EmailToken,
    TokenPurpose,
    User,
    UserRole,
    UserStatus,
)
from ledger.db.models.jobs import (
    ErrorType,
    Job,
    JobAttempt,
    JobRequest,
    JobStatus,
    JobType,
    ScheduleWatermark,
)
from ledger.db.models.market_data import (
    ArtifactKind,
    ManualNavSubmission,
    MetricType,
    Observation,
    ObservationHead,
    QualityStatus,
    RawArtifact,
)
from ledger.db.models.portfolio import (
    BankAccount,
    ImportBatch,
    ImportStatus,
    Position,
    Transaction,
    TransactionType,
)
from ledger.db.models.valuation import (
    Completeness,
    PortfolioSnapshot,
    PositionSnapshot,
    RunStatus,
    ValuationRun,
)

__all__ = [
    "ArtifactKind",
    "AuditEvent",
    "AuthSession",
    "BankAccount",
    "Base",
    "Completeness",
    "DataSource",
    "EmailToken",
    "ErrorType",
    "ImportBatch",
    "ImportStatus",
    "Institution",
    "InstitutionType",
    "Job",
    "JobAttempt",
    "JobRequest",
    "JobStatus",
    "JobType",
    "ManualNavSubmission",
    "MetricType",
    "Observation",
    "ObservationHead",
    "PortfolioSnapshot",
    "Position",
    "PositionSnapshot",
    "Product",
    "ProductDistribution",
    "ProductSourceMapping",
    "QualityStatus",
    "RawArtifact",
    "RunStatus",
    "ScheduleWatermark",
    "TokenPurpose",
    "Transaction",
    "TransactionType",
    "User",
    "UserRole",
    "UserStatus",
    "ValuationMethod",
    "ValuationRun",
]

from ledger.db.models.sources import AllowedDomain, SourceProposal, SourceProposalVersion

__all__ += ["AllowedDomain", "SourceProposal", "SourceProposalVersion"]
