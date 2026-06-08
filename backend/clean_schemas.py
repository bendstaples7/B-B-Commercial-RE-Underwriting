import re

file_path = "/home/jeffreyops/B-B-Commercial-RE-Underwriting/backend/app/schemas.py"

with open(file_path, "r") as f:
    content = f.read()

# 1. Remove extraneous \' characters introduced by previous faulty sed commands
# This regex looks for a backslash followed by a single quote at the end of a line, then removes them.
# It also handles cases where there might be spaces before the trailing \'
content = re.sub(r"\\'\\s*\\n", r"\n", content)
content = re.sub(r"\\'", "", content) # Catch any remaining non-newline trailing ones

# 2. Remove the duplicate StartAnalysisSchema content
# Using triple double quotes here so it doesn't conflict with the outer triple single quotes of the tool call
duplicate_block_after_pipeline = """\n\n\n\n    """Schema for starting a new analysis.\n\n    user_id is read from the X-User-Id header via g.user_id, not the body.\n    Unknown fields (including user_id sent by older clients) are silently dropped.\n    """\n    address = fields.Str(required=True, validate=validate.Length(min=5, max=500))\n    latitude = fields.Float(load_default=None, allow_none=True)\n    longitude = fields.Float(load_default=None, allow_none=True)\n"""

# Replace the duplicate block with just two newlines to maintain proper spacing
# The regex will also match if there are additional empty lines before/after.
content = content.replace(duplicate_block_after_pipeline, "\n\n")

# 3. Correct the ScenarioMetricsSchema docstring
# The old docstring had a malformed escape in the Python context.
# The file likely contains `\'` (literal backslash followed by single quote) inside the docstring.
# The sed commands were likely trying to fix this but were themselves creating issues.
# Now that global `\'` are removed, the docstring should look like this in the content string:
# `"""Schema for a single scenario\'s computed metrics."""`
# However, it might have been mangled. Let\'s try to fix it based on the assumption that it was `\'`
# Let\'s just replace the entire docstring to be safe.

old_docstring_scenario_metrics_pattern = r'\"\"\"Schema for a single scenario\\\'s computed metrics\\."\"\"'
new_docstring_scenario_metrics = '\"\"\"Schema for a single scenario\'s computed metrics.\"\"\"'
content = re.sub(old_docstring_scenario_metrics_pattern, new_docstring_scenario_metrics, content)

# Also check for the case where the backslash might have been completely removed leaving just a quote error.
old_docstring_scenario_metrics_pattern_no_backslash = r'\"\"\"Schema for a single scenario\'s computed metrics\\."\"\"'
content = re.sub(old_docstring_scenario_metrics_pattern_no_backslash, new_docstring_scenario_metrics, content)


# 4. Correct the VALID_SOURCE_TYPES comment
# This was initially `—` (em-dash), which caused a SyntaxError.
# A previous `sed` command was intended to fix this, but the file corruption interfered.
# Let\'s ensure it\'s fixed now.
old_comment_valid_source_types = '# Valid source types — defined here so LeadListQuerySchema can reference it'
new_comment_valid_source_types = '# Valid source types - defined here so LeadListQuerySchema can reference it'
content = content.replace(old_comment_valid_source_types, new_comment_valid_source_types)


with open(file_path, "w") as f:
    f.write(content)

print("Finished cleaning app/schemas.py")
