"""
File Workspace - Safe file operations with staging and rollback

Fixes the file system write strategy issues.
"""

from pathlib import Path
import shutil
from typing import List
from dataclasses import dataclass


@dataclass
class FileOperation:
    """Record of a file operation"""
    filepath: str
    content: str
    staged_path: Path
    final_path: Path


class FileWorkspace:
    """
    Safe file writing with:
    - Staging folder
    - Atomic commits
    - Rollback on failure
    - Overwrite rules
    """
    
    def __init__(self, project_root: Path, overwrite: bool = False):
        self.project_root = project_root
        self.staging = project_root / ".boom3_staging"
        self.overwrite = overwrite
        self.operations: List[FileOperation] = []
        
        # Create staging directory
        self.staging.mkdir(parents=True, exist_ok=True)
    
    def _validate_path(self, filepath: str) -> Path:
        """
        Resolve and validate that filepath stays within project_root.
        Raises ValueError for path-traversal attempts.
        """
        final_path = (self.project_root / filepath).resolve()
        try:
            final_path.relative_to(self.project_root.resolve())
        except ValueError:
            raise ValueError(
                f"Path traversal rejected: '{filepath}' resolves outside project root '{self.project_root}'"
            )
        return final_path

    def write_staged(self, filepath: str, content: str) -> bool:
        """
        Write file to staging area.

        filepath must be a relative path that stays within project_root.
        Any path that would escape the project root (e.g. '../../.bashrc')
        is rejected immediately before anything is written to disk.
        
        Args:
            filepath: Relative path (e.g., "backend/gui.py")
            content: File content
            
        Returns:
            True if staged successfully
        """
        try:
            # Validate before touching the filesystem
            final_path = self._validate_path(filepath)

            # Derive the staging path using the same relative portion
            relative = final_path.relative_to(self.project_root.resolve())
            staged_path = self.staging / relative
            staged_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write to staging
            staged_path.write_text(content, encoding='utf-8')
            
            # Record operation
            operation = FileOperation(
                filepath=filepath,
                content=content,
                staged_path=staged_path,
                final_path=final_path
            )
            self.operations.append(operation)
            
            return True
        
        except Exception as e:
            print(f"Failed to stage {filepath}: {e}")
            return False
    
    def commit(self) -> bool:
        """
        Commit all staged files to final locations
        
        This is atomic - either all succeed or all fail.
        
        Returns:
            True if all files committed successfully
        """
        try:
            # Check for conflicts if overwrite=False
            if not self.overwrite:
                conflicts = []
                for op in self.operations:
                    if op.final_path.exists():
                        conflicts.append(str(op.final_path))
                
                if conflicts:
                    print(f"⚠️  Files already exist (use overwrite=True to replace):")
                    for conflict in conflicts:
                        print(f"   - {conflict}")
                    return False
            
            # Commit all files
            committed = []
            try:
                for op in self.operations:
                    # Create directory
                    op.final_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Copy from staging to final
                    shutil.copy2(op.staged_path, op.final_path)
                    committed.append(op.final_path)
                
                print(f"✅ Committed {len(committed)} files")
                return True
            
            except Exception as e:
                # Rollback committed files
                print(f"❌ Commit failed: {e}")
                print("   Rolling back...")
                for path in committed:
                    try:
                        path.unlink()
                    except:
                        pass
                return False
        
        finally:
            # Clean up staging
            self.cleanup_staging()
    
    def rollback(self):
        """Delete all staged files without committing"""
        print(f"🔄 Rolling back {len(self.operations)} operations")
        self.cleanup_staging()
        self.operations.clear()
    
    def cleanup_staging(self):
        """Remove staging directory"""
        if self.staging.exists():
            shutil.rmtree(self.staging)
    
    def list_staged(self) -> List[str]:
        """List all staged files"""
        return [op.filepath for op in self.operations]
    
    def get_staged_content(self, filepath: str) -> str:
        """Get content of a staged file"""
        for op in self.operations:
            if op.filepath == filepath:
                return op.content
        return None


# Integration with FileManager
class SafeFileManager:
    """
    Enhanced FileManager using FileWorkspace
    
    Replaces the basic FileManager with safe operations.
    """
    
    def __init__(self, project_root: Path, overwrite: bool = False):
        self.project_root = project_root
        self.workspace = FileWorkspace(project_root, overwrite=overwrite)
    
    def write_file(self, output) -> bool:
        """Stage a file for writing"""
        return self.workspace.write_staged(output.filepath, output.code)
    
    def read_file(self, filepath: str) -> str:
        """Read a file (checks staging first, then final location)"""
        # Check if in staging
        content = self.workspace.get_staged_content(filepath)
        if content:
            return content
        
        # Check final location
        final_path = self.project_root / filepath
        if final_path.exists():
            return final_path.read_text(encoding='utf-8')
        
        return None
    
    def commit_all(self) -> bool:
        """Commit all staged files"""
        return self.workspace.commit()
    
    def rollback(self):
        """Rollback all changes"""
        self.workspace.rollback()
    
    def list_created_files(self) -> List[str]:
        """List files that will be created"""
        return self.workspace.list_staged()


if __name__ == "__main__":
    # Example usage
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = FileWorkspace(Path(tmpdir))
        
        # Stage some files
        workspace.write_staged("backend/gui.py", "def main(): pass")
        workspace.write_staged("backend/logic.py", "def process(): pass")
        workspace.write_staged("tests/test_gui.py", "def test_gui(): pass")
        
        print(f"Staged files: {workspace.list_staged()}")
        
        # Commit
        success = workspace.commit()
        print(f"Commit success: {success}")
        
        # Check files exist
        for filepath in ["backend/gui.py", "backend/logic.py", "tests/test_gui.py"]:
            path = Path(tmpdir) / filepath
            print(f"{filepath} exists: {path.exists()}")
