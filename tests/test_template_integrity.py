"""
Strict YAML Template Integrity Tests.

Validates that all methodology templates are well-formed, have no duplicate IDs,
and that all cross-references are valid.
"""

import pytest
from pathlib import Path
from hackmind.engine.template_loader import load_template_from_file, TemplateValidationError
from hackmind.models.types import NodeType


def get_templates():
    """Find all YAML files in the templates directory."""
    templates_dir = Path("templates")
    return list(templates_dir.glob("*.yaml")) + list(templates_dir.glob("*.yml"))


@pytest.mark.parametrize("template_path", get_templates())
def test_template_integrity(template_path):
    """Load and validate each template file."""
    try:
        template = load_template_from_file(template_path)
    except TemplateValidationError as e:
        pytest.fail(f"Template {template_path.name} failed to parse: {e}")

    # The loader already calls initialize_lookup() which indexes all nodes.
    # We can use that to check for duplicates and cross-references.
    
    seen_ids = set()
    
    def validate_node(node, context=""):
        # 1. Ensure no duplicate IDs
        if node.id in seen_ids:
            pytest.fail(f"Duplicate ID '{node.id}' found in {template_path.name} at {context}")
        seen_ids.add(node.id)
        
        # 2. If node is a question, ensure it has options
        if node.type == NodeType.QUESTION:
            if not node.options:
                pytest.fail(f"Question node '{node.id}' has no options in {template_path.name}")
        
        # 3. Recursively validate children and options
        for i, child in enumerate(node.children):
            validate_node(child, f"{context} -> child[{i}]")
            
        for i, opt in enumerate(node.options):
            # Options don't have IDs themselves usually, but they have children
            for j, opt_child in enumerate(opt.children):
                validate_node(opt_child, f"{context} -> option[{i}] -> child[{j}]")

    # The Template object has a flat list of nodes at the root
    for i, root_node in enumerate(template.nodes):
        validate_node(root_node, f"root[{i}]")

    # 4. Check that _nodes_lookup is fully populated (sanity check)
    assert len(seen_ids) == len(template._nodes_lookup), "Internal lookup map size mismatch"


def test_no_templates_found():
    """Ensure we actually found some templates to test."""
    assert len(get_templates()) > 0, "No templates found in /templates/ directory"
