"""
Production Validation & Retry Engine

This is the ENFORCEMENT layer - makes contracts actually work.
"""

from typing import List, Tuple, Dict, Any
from enum import Enum
from dataclasses import dataclass

from contracts.agent_contracts import AgentDeliverable, CodeOutput, WiringContract


class FailureReason(Enum):
    """Why validation failed"""
    SCHEMA_INVALID = "schema_invalid"
    FILE_OWNERSHIP_VIOLATED = "file_ownership_violated"
    INTERFACE_VIOLATED = "interface_violated"
    STYLE_VIOLATED = "style_violated"
    WIRING_INVALID = "wiring_invalid"
    COMPILATION_FAILED = "compilation_failed"
    TESTS_FAILED = "tests_failed"


@dataclass
class ValidationResult:
    """Result of validation"""
    valid: bool
    errors: List[str]
    warnings: List[str]
    failure_reason: FailureReason = None


class DeliverableValidator:
    """
    HARD VALIDATION at agent boundaries
    
    This is what makes contracts actually work.
    """
    
    def validate_complete(self, deliverable: AgentDeliverable) -> ValidationResult:
        """Run ALL validation checks"""
        errors = []
        warnings = []
        failure_reason = None
        
        # 1. Schema validation
        if not deliverable.validate():
            errors.append("Deliverable schema validation failed")
            failure_reason = FailureReason.SCHEMA_INVALID
        
        # 2. File ownership validation
        ownership_valid, ownership_errors = self._validate_file_ownership(deliverable)
        if not ownership_valid:
            errors.extend(ownership_errors)
            failure_reason = FailureReason.FILE_OWNERSHIP_VIOLATED
        
        # 3. Output schema validation
        for output in deliverable.outputs:
            if not output.validate():
                errors.append(f"Invalid output schema for {output.filepath}")
                failure_reason = FailureReason.SCHEMA_INVALID
        
        # 4. Wiring validation
        for wire in deliverable.wiring:
            if not wire.validate():
                errors.append(f"Invalid wiring: {wire.from_component} -> {wire.to_component}")
                failure_reason = FailureReason.WIRING_INVALID
        
        # 5. Code style validation (warnings only)
        for output in deliverable.outputs:
            if output.language == "python":
                style_issues = self._validate_python_style(output.code)
                if style_issues:
                    warnings.extend(style_issues)
        
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            failure_reason=failure_reason
        )
    
    def _validate_file_ownership(self, deliverable: AgentDeliverable) -> Tuple[bool, List[str]]:
        """Validate agent only created files it owns"""
        from contracts.agent_contracts import FILE_OWNERSHIP
        
        allowed_patterns = FILE_OWNERSHIP.get(deliverable.agent_role, [])
        errors = []
        
        for output in deliverable.outputs:
            filename = output.filepath.split('/')[-1]
            
            # Check if filename matches any allowed pattern
            allowed = False
            for pattern in allowed_patterns:
                if self._matches_pattern(filename, pattern):
                    allowed = True
                    break
            
            if not allowed:
                errors.append(
                    f"{deliverable.agent_role.value} tried to create {filename} "
                    f"but can only create: {allowed_patterns}"
                )
        
        return len(errors) == 0, errors
    
    def _matches_pattern(self, filename: str, pattern: str) -> bool:
        """Simple glob matching"""
        if '*' in pattern:
            prefix = pattern.split('*')[0]
            suffix = pattern.split('*')[-1]
            return filename.startswith(prefix) and filename.endswith(suffix)
        return filename == pattern
    
    def _validate_python_style(self, code: str) -> List[str]:
        """Basic Python style checks"""
        issues = []
        lines = code.split('\n')
        
        # Check for tabs
        for i, line in enumerate(lines, 1):
            if '\t' in line:
                issues.append(f"Line {i}: Uses tabs instead of spaces")
        
        # Check line length
        for i, line in enumerate(lines, 1):
            if len(line) > 100:
                issues.append(f"Line {i}: Line too long ({len(line)} chars)")
        
        return issues


class WiringLinker:
    """
    Lightweight wiring verifier.

    Older versions treated agent-declared wiring as a hard contract and failed
    projects whenever an agent mentioned old template names such as app.py,
    services.py, backend_logic, database.py, etc. That blocked larger apps like
    a Lovable/Bolt-style builder even when the generated code could be tested
    and repaired.

    This pass now keeps wiring useful for visibility, but only hard-fails on
    high-confidence problems. Generated applications are finally judged by the
    real pipeline afterwards: dependencies, pytest, repair, rerun, and prompt
    compliance.
    """

    def link_and_verify(self, deliverables: List[AgentDeliverable]) -> ValidationResult:
        """Run tolerant linker checks on all deliverables."""
        errors = []
        warnings = []

        provided_symbols = self._build_symbol_table(deliverables)

        # Agent-declared wiring is advisory. The LLM often emits stale component
        # names from the built-in template; log those as warnings instead of
        # killing the whole run before tests/repair can execute.
        for deliverable in deliverables:
            for wire in deliverable.wiring:
                if wire.to_component not in provided_symbols:
                    warnings.append(
                        f"Wiring warning: {wire.to_component} not found "
                        f"(referenced by {wire.from_component}); will rely on tests/repair"
                    )
                    continue

                if wire.to_symbol not in provided_symbols[wire.to_component]:
                    warnings.append(
                        f"Wiring warning: {wire.to_component}.{wire.to_symbol} not found "
                        f"(referenced by {wire.from_component}); will rely on tests/repair"
                    )

        # imports_from is also agent-declared metadata, not parsed ground truth.
        # Missing modules may be stdlib/third-party/packages; missing symbols may
        # be aliases or dynamically provided. Warn only. Python import/test runs
        # later provide the real signal and trigger auto-repair if broken.
        for deliverable in deliverables:
            for output in deliverable.outputs:
                for module, symbols in output.imports_from.items():
                    if module not in provided_symbols:
                        warnings.append(
                            f"Import metadata warning: {output.filepath} imports from {module}; "
                            "will verify by running tests"
                        )
                        continue

                    for symbol in symbols:
                        if symbol not in provided_symbols[module]:
                            warnings.append(
                                f"Import metadata warning: {output.filepath} imports {symbol} "
                                f"from {module}, but metadata does not list it as exported; "
                                "will verify by running tests"
                            )

        return ValidationResult(
            valid=True,
            errors=errors,
            warnings=warnings,
            failure_reason=None
        )

    def _build_symbol_table(self, deliverables: List[AgentDeliverable]) -> Dict[str, List[str]]:
        """Build table of what each component claims to provide."""
        symbols = {}

        for deliverable in deliverables:
            for output in deliverable.outputs:
                component = output.filepath.split('/')[-1].rsplit('.', 1)[0]
                symbols[component] = output.exports or []

        return symbols


class RetryPolicy:
    """
    Centralized retry logic
    
    Determines when and how to retry failed agent work.
    """
    
    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts
        self.attempt_count = {}  # task_id -> count
    
    def should_retry(self, task_id: str, failure_reason: FailureReason) -> bool:
        """Decide if we should retry"""
        attempts = self.attempt_count.get(task_id, 0)
        
        # Never retry beyond max
        if attempts >= self.max_attempts:
            return False
        
        # Always retry on schema/validation issues
        if failure_reason in [
            FailureReason.SCHEMA_INVALID,
            FailureReason.FILE_OWNERSHIP_VIOLATED,
            FailureReason.INTERFACE_VIOLATED,
            FailureReason.STYLE_VIOLATED
        ]:
            return True
        
        # Retry on wiring issues once
        if failure_reason == FailureReason.WIRING_INVALID and attempts < 2:
            return True
        
        # Retry on compilation/test failures
        if failure_reason in [FailureReason.COMPILATION_FAILED, FailureReason.TESTS_FAILED]:
            return True
        
        return False
    
    def record_attempt(self, task_id: str):
        """Record an attempt"""
        self.attempt_count[task_id] = self.attempt_count.get(task_id, 0) + 1
    
    def get_attempt_count(self, task_id: str) -> int:
        """Get current attempt count"""
        return self.attempt_count.get(task_id, 0)
    
    def get_retry_strategy(self, failure_reason: FailureReason, attempt: int) -> str:
        """Get guidance for retry"""
        if failure_reason == FailureReason.SCHEMA_INVALID:
            return "Your output did not match the required schema. Follow the CodeOutput schema EXACTLY."
        
        if failure_reason == FailureReason.FILE_OWNERSHIP_VIOLATED:
            return "You tried to create files you don't own. Only create files in your allowed list."
        
        if failure_reason == FailureReason.WIRING_INVALID:
            if attempt == 1:
                return "Your wiring connections reference components/symbols that don't exist. Check carefully."
            else:
                return "Wiring still invalid. List available components and their exports first."
        
        if failure_reason == FailureReason.COMPILATION_FAILED:
            return "Generated code has syntax errors. Fix all Python syntax issues."
        
        if failure_reason == FailureReason.TESTS_FAILED:
            return "Tests failed. Fix the code to make tests pass."
        
        return "Please fix the issues and try again."


# Integration example
def validate_and_retry_loop(agent, task, context, retry_policy, validator, linker):
    """
    Example of how validation + retry work together
    """
    task_id = task.get('id', 'unknown')
    
    while True:
        attempt = retry_policy.get_attempt_count(task_id) + 1
        
        # Execute task
        deliverable = agent.execute_task(task, context)
        
        # Validate
        validation = validator.validate_complete(deliverable)
        
        if validation.valid:
            # Also run linker check (needs all deliverables, so might be deferred)
            return deliverable
        
        # Check if we should retry
        if not retry_policy.should_retry(task_id, validation.failure_reason):
            raise ValueError(f"Validation failed after {attempt} attempts: {validation.errors}")
        
        # Record attempt and get retry strategy
        retry_policy.record_attempt(task_id)
        retry_guidance = retry_policy.get_retry_strategy(validation.failure_reason, attempt)
        
        # Update context with errors and retry guidance
        context = f"{context}\n\nPREVIOUS ATTEMPT FAILED:\n{validation.errors}\n\n{retry_guidance}"
        
        # Loop to retry


if __name__ == "__main__":
    # Example usage
    from contracts.agent_contracts import AgentDeliverable, AgentRole, CodeOutput
    
    # Test validation
    validator = DeliverableValidator()
    
    # Valid deliverable
    valid_output = CodeOutput(
        code="def hello(): pass",
        filepath="gui.py",
        language="python",
        exports=["hello"]
    )
    
    valid_deliverable = AgentDeliverable(
        agent_role=AgentRole.GUI_BUILDER,
        outputs=[valid_output],
        wiring=[],
        tests_generated=[],
        documentation="Test"
    )
    
    result = validator.validate_complete(valid_deliverable)
    print(f"Valid deliverable: {result.valid}")
    
    # Invalid deliverable (wrong file)
    invalid_output = CodeOutput(
        code="def backend(): pass",
        filepath="logic.py",  # Backend file!
        language="python"
    )
    
    invalid_deliverable = AgentDeliverable(
        agent_role=AgentRole.GUI_BUILDER,  # GUI agent!
        outputs=[invalid_output],
        wiring=[],
        tests_generated=[],
        documentation=""
    )
    
    result = validator.validate_complete(invalid_deliverable)
    print(f"Invalid deliverable: {result.valid}")
    print(f"Errors: {result.errors}")
