from processing.diff_processor import DiffProcessor, DiffHunk, ChangedChunk


def test_process_diff():
    """Test diff processing."""
    processor = DiffProcessor()

    diff_content = """
--- a/example.py
+++ b/example.py
@@ -1,5 +1,7 @@
 def hello_world():
-    print("Hello, World!")
+    print("Hello, Beautiful World!")
+    return "greeting"
 
 class Calculator:
     def add(self, a, b):
+        # Added validation
         return a + b
"""

    hunks = processor.process_diff(diff_content)

    assert len(hunks) == 1
    assert hunks[0].file_path == "example.py"
    assert hunks[0].old_start == 1
    assert hunks[0].new_start == 1
    assert len(hunks[0].added_lines) == 3
    assert len(hunks[0].removed_lines) == 1
    assert '    print("Hello, Beautiful World!")' in hunks[0].added_lines
    assert '    return "greeting"' in hunks[0].added_lines
    assert '        # Added validation' in hunks[0].added_lines
    assert '    print("Hello, World!")' in hunks[0].removed_lines


def test_create_query_from_changes():
    """Test query generation from changes."""
    processor = DiffProcessor()

    # Create mock changed chunks
    from core.chunker import CodeChunk

    changed_chunks = [
        ChangedChunk(
            chunk=CodeChunk(
                content="def hello(): pass",
                file_path="test.py",
                start_line=1,
                end_line=2,
                chunk_type="function",
                name="hello",
            ),
            change_type="modified",
        ),
        ChangedChunk(
            chunk=CodeChunk(
                content="class Calculator: pass",
                file_path="test.py",
                start_line=4,
                end_line=5,
                chunk_type="class",
                name="Calculator",
            ),
            change_type="added",
        ),
    ]

    query = processor.create_query_from_changes(changed_chunks)

    assert "hello" in query
    assert "Calculator" in query
    assert "function" in query
    assert "class" in query


def test_determine_change_type():
    """Test change type determination."""
    processor = DiffProcessor()

    # Added only
    hunk_added = DiffHunk(
        file_path="test.py",
        old_start=1,
        new_start=1,
        added_lines=["new line"],
        removed_lines=[],
    )

    assert processor._determine_change_type(hunk_added) == "added"

    # Removed only
    hunk_removed = DiffHunk(
        file_path="test.py",
        old_start=1,
        new_start=1,
        added_lines=[],
        removed_lines=["old line"],
    )

    assert processor._determine_change_type(hunk_removed) == "removed"

    # Modified
    hunk_modified = DiffHunk(
        file_path="test.py",
        old_start=1,
        new_start=1,
        added_lines=["new line"],
        removed_lines=["old line"],
    )

    assert processor._determine_change_type(hunk_modified) == "modified"


def test_chunk_overlaps_hunk():
    """Test chunk-hunk overlap detection."""
    processor = DiffProcessor()

    from core.chunker import CodeChunk

    chunk = CodeChunk(
        content="def hello(): pass",
        file_path="test.py",
        start_line=5,
        end_line=10,
        chunk_type="function",
        name="hello",
    )

    # Overlapping hunk
    hunk_overlap = DiffHunk(
        file_path="test.py",
        old_start=8,
        new_start=8,
        added_lines=["new line"],
        removed_lines=[],
    )

    assert processor._chunk_overlaps_hunk(chunk, hunk_overlap)

    # Non-overlapping hunk
    hunk_no_overlap = DiffHunk(
        file_path="test.py",
        old_start=15,
        new_start=15,
        added_lines=["new line"],
        removed_lines=[],
    )

    assert not processor._chunk_overlaps_hunk(chunk, hunk_no_overlap)


def test_empty_diff():
    """Test handling of empty diff."""
    processor = DiffProcessor()

    hunks = processor.process_diff("")
    assert len(hunks) == 0

    hunks = processor.process_diff("invalid diff content")
    assert len(hunks) == 0


def test_multiple_files_diff():
    """Test processing diff with multiple files."""
    processor = DiffProcessor()

    diff_content = """
--- a/file1.py
+++ b/file1.py
@@ -1,2 +1,3 @@
 def func1():
     pass
+    return None
--- a/file2.py
+++ b/file2.py
@@ -1,2 +1,2 @@
-def func2():
+def func2_renamed():
     pass
"""

    hunks = processor.process_diff(diff_content)

    assert len(hunks) == 2
    assert hunks[0].file_path == "file1.py"
    assert hunks[1].file_path == "file2.py"
