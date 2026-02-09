"""
InstantTrade Network (ITN) - Artifact Versioning System
Version: 1.0.0
Generated: 2026-02-08

Provides version control, migration paths, and rollback capabilities
for invariant artifacts across system evolution.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from enum import Enum
import json

# ============================================
# VERSION TYPES
# ============================================

class ChangeType(Enum):
    MAJOR = "major"  # Breaking change - requires migration
    MINOR = "minor"  # New feature - backward compatible
    PATCH = "patch"  # Bug fix - transparent

class MigrationStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"

# ============================================
# ARTIFACT VERSION
# ============================================

@dataclass
class ArtifactVersion:
    """Represents a specific version of the invariant artifacts."""
    
    version: str  # Semantic versioning: MAJOR.MINOR.PATCH
    date: datetime
    changes: List[str]
    change_type: ChangeType
    migration: Optional[Callable[[Dict], Dict]] = None
    rollback: Optional[Callable[[Dict], Dict]] = None
    verification: Optional[Callable[[Dict], bool]] = None
    
    # Metadata
    author: str = "system"
    requires_downtime: bool = False
    estimated_duration_minutes: int = 0
    
    def apply_migration(self, current_state: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate state to this version."""
        
        if self.migration is None:
            print(f"[INFO] Version {self.version} has no migration - no changes to state")
            return current_state
        
        print(f"[MIGRATION] Migrating to version {self.version}...")
        print(f"[MIGRATION] Changes: {', '.join(self.changes)}")
        
        try:
            new_state = self.migration(current_state)
            
            # Verify migration succeeded
            if self.verification and not self.verification(new_state):
                raise Exception(f"Migration verification failed for version {self.version}")
            
            print(f"[MIGRATION] ✅ Successfully migrated to {self.version}")
            return new_state
            
        except Exception as e:
            print(f"[MIGRATION] ❌ Migration failed: {e}")
            
            # Attempt rollback
            if self.rollback:
                print(f"[MIGRATION] Attempting rollback...")
                return self.apply_rollback(current_state)
            else:
                raise Exception(f"Migration failed and no rollback available: {e}")
    
    def apply_rollback(self, current_state: Dict[str, Any]) -> Dict[str, Any]:
        """Rollback to previous version."""
        
        if self.rollback is None:
            raise Exception(f"No rollback available for version {self.version}")
        
        print(f"[ROLLBACK] Rolling back from version {self.version}...")
        
        try:
            previous_state = self.rollback(current_state)
            print(f"[ROLLBACK] ✅ Successfully rolled back from {self.version}")
            return previous_state
            
        except Exception as e:
            raise Exception(f"Rollback failed: {e}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize version metadata."""
        return {
            'version': self.version,
            'date': self.date.isoformat(),
            'changes': self.changes,
            'change_type': self.change_type.value,
            'author': self.author,
            'requires_downtime': self.requires_downtime,
            'estimated_duration_minutes': self.estimated_duration_minutes
        }

# ============================================
# VERSION HISTORY
# ============================================

class VersionHistory:
    """Manages complete version history of artifacts."""
    
    def __init__(self):
        self.versions: List[ArtifactVersion] = []
        self.current_version: Optional[str] = None
    
    def add_version(self, version: ArtifactVersion):
        """Add new version to history."""
        
        # Verify version number is valid
        if not self._is_valid_version(version.version):
            raise ValueError(f"Invalid version number: {version.version}")
        
        # Verify version doesn't already exist
        if any(v.version == version.version for v in self.versions):
            raise ValueError(f"Version {version.version} already exists")
        
        # Verify version is newer than current
        if self.versions and self._compare_versions(version.version, self.versions[-1].version) <= 0:
            raise ValueError(f"Version {version.version} is not newer than {self.versions[-1].version}")
        
        self.versions.append(version)
        print(f"[VERSION] Added version {version.version}")
    
    def get_version(self, version_str: str) -> Optional[ArtifactVersion]:
        """Get specific version."""
        for v in self.versions:
            if v.version == version_str:
                return v
        return None
    
    def get_latest_version(self) -> Optional[ArtifactVersion]:
        """Get most recent version."""
        return self.versions[-1] if self.versions else None
    
    def get_migration_path(self, from_version: str, to_version: str) -> List[ArtifactVersion]:
        """Get ordered list of versions needed to migrate from -> to."""
        
        from_idx = self._get_version_index(from_version)
        to_idx = self._get_version_index(to_version)
        
        if from_idx is None:
            raise ValueError(f"Version {from_version} not found")
        if to_idx is None:
            raise ValueError(f"Version {to_version} not found")
        
        if from_idx >= to_idx:
            raise ValueError(f"Cannot migrate from {from_version} to {to_version} (already at or past target)")
        
        # Return versions in order from (from_version, to_version]
        return self.versions[from_idx + 1:to_idx + 1]
    
    def _get_version_index(self, version_str: str) -> Optional[int]:
        """Get index of version in history."""
        for i, v in enumerate(self.versions):
            if v.version == version_str:
                return i
        return None
    
    def _is_valid_version(self, version_str: str) -> bool:
        """Verify version follows semantic versioning."""
        parts = version_str.split('.')
        if len(parts) != 3:
            return False
        return all(p.isdigit() for p in parts)
    
    def _compare_versions(self, v1: str, v2: str) -> int:
        """Compare two version strings. Returns -1 (v1<v2), 0 (equal), 1 (v1>v2)."""
        v1_parts = [int(p) for p in v1.split('.')]
        v2_parts = [int(p) for p in v2.split('.')]
        
        for i in range(3):
            if v1_parts[i] < v2_parts[i]:
                return -1
            elif v1_parts[i] > v2_parts[i]:
                return 1
        
        return 0
    
    def export_history(self, filepath: str):
        """Export version history to JSON."""
        history_data = {
            'current_version': self.current_version,
            'versions': [v.to_dict() for v in self.versions]
        }
        
        with open(filepath, 'w') as f:
            json.dump(history_data, f, indent=2)
        
        print(f"[EXPORT] Version history exported to {filepath}")

# ============================================
# MIGRATION MANAGER
# ============================================

class MigrationManager:
    """Orchestrates migrations with safety checks."""
    
    def __init__(self, version_history: VersionHistory):
        self.version_history = version_history
        self.migration_log: List[Dict] = []
    
    def migrate(self, current_state: Dict, target_version: str) -> Dict[str, Any]:
        """Execute migration from current state to target version."""
        
        current_version = current_state.get('version', '1.0.0')
        
        print(f"\n{'='*60}")
        print(f"MIGRATION: {current_version} → {target_version}")
        print(f"{'='*60}\n")
        
        # Get migration path
        try:
            migration_path = self.version_history.get_migration_path(current_version, target_version)
        except ValueError as e:
            print(f"[ERROR] Cannot determine migration path: {e}")
            return current_state
        
        if not migration_path:
            print(f"[INFO] Already at version {target_version}")
            return current_state
        
        print(f"[PLAN] Migration path: {' → '.join(v.version for v in migration_path)}")
        
        # Estimate total time
        total_minutes = sum(v.estimated_duration_minutes for v in migration_path)
        requires_downtime = any(v.requires_downtime for v in migration_path)
        
        print(f"[PLAN] Estimated duration: {total_minutes} minutes")
        print(f"[PLAN] Requires downtime: {requires_downtime}")
        print()
        
        # Create migration log entry
        migration_id = f"migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        log_entry = {
            'migration_id': migration_id,
            'from_version': current_version,
            'to_version': target_version,
            'path': [v.version for v in migration_path],
            'started_at': datetime.now(),
            'status': MigrationStatus.IN_PROGRESS.value
        }
        
        # Execute migrations in order
        migrated_state = current_state.copy()
        
        try:
            for version in migration_path:
                print(f"\n[STEP] Applying version {version.version}")
                migrated_state = version.apply_migration(migrated_state)
                migrated_state['version'] = version.version
            
            # Success
            log_entry['status'] = MigrationStatus.COMPLETED.value
            log_entry['completed_at'] = datetime.now()
            
            print(f"\n{'='*60}")
            print(f"✅ MIGRATION SUCCESSFUL: Now at version {target_version}")
            print(f"{'='*60}\n")
            
            return migrated_state
            
        except Exception as e:
            # Failure - log and re-raise
            log_entry['status'] = MigrationStatus.FAILED.value
            log_entry['error'] = str(e)
            log_entry['failed_at'] = datetime.now()
            
            self.migration_log.append(log_entry)
            
            print(f"\n{'='*60}")
            print(f"❌ MIGRATION FAILED: {e}")
            print(f"{'='*60}\n")
            
            raise
        
        finally:
            self.migration_log.append(log_entry)
    
    def rollback_to_version(self, current_state: Dict, target_version: str) -> Dict[str, Any]:
        """Rollback to previous version."""
        
        current_version = current_state.get('version', '1.0.0')
        
        print(f"\n{'='*60}")
        print(f"ROLLBACK: {current_version} → {target_version}")
        print(f"{'='*60}\n")
        
        # Get versions to rollback (in reverse order)
        from_idx = self.version_history._get_version_index(target_version)
        to_idx = self.version_history._get_version_index(current_version)
        
        if from_idx is None or to_idx is None:
            raise ValueError("Invalid version for rollback")
        
        rollback_versions = list(reversed(self.version_history.versions[from_idx + 1:to_idx + 1]))
        
        print(f"[PLAN] Rollback path: {' ← '.join(v.version for v in rollback_versions)}")
        
        # Execute rollbacks
        rolled_back_state = current_state.copy()
        
        for version in rollback_versions:
            print(f"\n[STEP] Rolling back {version.version}")
            rolled_back_state = version.apply_rollback(rolled_back_state)
        
        rolled_back_state['version'] = target_version
        
        print(f"\n{'='*60}")
        print(f"✅ ROLLBACK SUCCESSFUL: Now at version {target_version}")
        print(f"{'='*60}\n")
        
        return rolled_back_state

# ============================================
# EXAMPLE VERSION DEFINITIONS
# ============================================

def create_itn_version_history() -> VersionHistory:
    """Create complete version history for InstantTrade Network."""
    
    history = VersionHistory()
    
    # Version 1.0.0 - Initial release
    history.add_version(ArtifactVersion(
        version="1.0.0",
        date=datetime(2026, 2, 1),
        changes=[
            "Initial implementation: 14 core invariants",
            "Invoice creation and validation",
            "Basic settlement flow",
            "Fraud detection"
        ],
        change_type=ChangeType.MAJOR,
        migration=None,  # No migration from nothing
        rollback=None,
        author="itn_team",
        requires_downtime=True,
        estimated_duration_minutes=120
    ))
    
    # Version 1.1.0 - Add temporal invariants
    def migrate_to_1_1_0(state: Dict) -> Dict:
        """Add timestamp tracking for temporal invariants."""
        state['timestamps'] = {
            'settlement_deadlines': {},
            'fraud_score_calculated': {},
            'fx_rate_fetched': {}
        }
        return state
    
    def rollback_from_1_1_0(state: Dict) -> Dict:
        """Remove timestamp tracking."""
        if 'timestamps' in state:
            del state['timestamps']
        return state
    
    def verify_1_1_0(state: Dict) -> bool:
        """Verify timestamps exist."""
        return 'timestamps' in state
    
    history.add_version(ArtifactVersion(
        version="1.1.0",
        date=datetime(2026, 2, 5),
        changes=[
            "Added INV-201: Settlement within 5 seconds",
            "Added INV-202: Fraud score freshness",
            "Added INV-204: FX rate freshness",
            "Added timestamp tracking infrastructure"
        ],
        change_type=ChangeType.MINOR,
        migration=migrate_to_1_1_0,
        rollback=rollback_from_1_1_0,
        verification=verify_1_1_0,
        author="itn_team",
        requires_downtime=False,
        estimated_duration_minutes=15
    ))
    
    # Version 2.0.0 - Multi-currency support
    def migrate_to_2_0_0(state: Dict) -> Dict:
        """Add multi-currency support."""
        # Add currency field to all existing invoices (default USD)
        if 'invoices' in state:
            for invoice_id, invoice in state['invoices'].items():
                if 'currency' not in invoice:
                    invoice['currency'] = 'USD'
                    invoice['fx_rate'] = 1.0
                    invoice['fx_timestamp'] = datetime.now()
        
        # Add FX rate cache
        state['fx_rates'] = {
            'USD': 1.0,
            'EUR': 1.08,
            'GBP': 1.27,
            'JPY': 0.0067
        }
        
        return state
    
    def rollback_from_2_0_0(state: Dict) -> Dict:
        """Remove multi-currency fields."""
        if 'invoices' in state:
            for invoice_id, invoice in state['invoices'].items():
                if 'currency' in invoice:
                    del invoice['currency']
                if 'fx_rate' in invoice:
                    del invoice['fx_rate']
                if 'fx_timestamp' in invoice:
                    del invoice['fx_timestamp']
        
        if 'fx_rates' in state:
            del state['fx_rates']
        
        return state
    
    def verify_2_0_0(state: Dict) -> bool:
        """Verify multi-currency fields exist."""
        if 'fx_rates' not in state:
            return False
        if 'invoices' in state:
            for invoice in state['invoices'].values():
                if 'currency' not in invoice:
                    return False
        return True
    
    history.add_version(ArtifactVersion(
        version="2.0.0",
        date=datetime(2026, 2, 10),
        changes=[
            "Added multi-currency support (USD, EUR, GBP, JPY)",
            "Added INV-204: FX rate freshness enforcement",
            "Modified invoice schema to include currency field",
            "Added FX rate caching layer"
        ],
        change_type=ChangeType.MAJOR,
        migration=migrate_to_2_0_0,
        rollback=rollback_from_2_0_0,
        verification=verify_2_0_0,
        author="itn_team",
        requires_downtime=True,
        estimated_duration_minutes=45
    ))
    
    # Version 2.1.0 - Security enhancements
    def migrate_to_2_1_0(state: Dict) -> Dict:
        """Add security features."""
        state['security'] = {
            'rate_limits': {},
            'failed_auth_attempts': {},
            'signature_keys': {}
        }
        return state
    
    def rollback_from_2_1_0(state: Dict) -> Dict:
        """Remove security features."""
        if 'security' in state:
            del state['security']
        return state
    
    history.add_version(ArtifactVersion(
        version="2.1.0",
        date=datetime(2026, 2, 15),
        changes=[
            "Added INV-403: Cryptographic signature required",
            "Added INV-404: Rate limiting",
            "Enhanced auth logging",
            "Added signature verification infrastructure"
        ],
        change_type=ChangeType.MINOR,
        migration=migrate_to_2_1_0,
        rollback=rollback_from_2_1_0,
        author="security_team",
        requires_downtime=False,
        estimated_duration_minutes=20
    ))
    
    return history

# ============================================
# USAGE EXAMPLE
# ============================================

def example_migration():
    """Demonstrate version migration."""
    
    print("\n" + "="*80)
    print("INSTANTTRADE NETWORK - ARTIFACT VERSION MIGRATION DEMO")
    print("="*80 + "\n")
    
    # Create version history
    history = create_itn_version_history()
    
    # Initial system state (version 1.0.0)
    system_state = {
        'version': '1.0.0',
        'invoices': {
            'INV-001': {
                'id': 'INV-001',
                'amount': 50000,
                'status': 'SETTLED'
            }
        },
        'settlements': []
    }
    
    print(f"Initial State: {json.dumps(system_state, indent=2)}\n")
    
    # Create migration manager
    manager = MigrationManager(history)
    
    # Migrate to version 2.1.0
    try:
        migrated_state = manager.migrate(system_state, '2.1.0')
        print(f"\nMigrated State: {json.dumps(migrated_state, indent=2, default=str)}\n")
        
        # Demonstrate rollback
        rolled_back_state = manager.rollback_to_version(migrated_state, '1.1.0')
        print(f"\nRolled Back State: {json.dumps(rolled_back_state, indent=2, default=str)}\n")
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}\n")
    
    # Export version history
    history.export_history('itn_version_history.json')
    
    print("\n" + "="*80)
    print("Migration log:")
    print("="*80)
    for entry in manager.migration_log:
        print(f"\n{entry['migration_id']}:")
        print(f"  {entry['from_version']} → {entry['to_version']}")
        print(f"  Status: {entry['status']}")
        if 'error' in entry:
            print(f"  Error: {entry['error']}")

if __name__ == "__main__":
    example_migration()
