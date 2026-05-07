"""Test _sanitize_comment validator in schemas.py"""
import sys
sys.path.insert(0, ".")
from src.dashboard.schemas import AIFeedbackCreate, _sanitize_comment

tests_passed = 0

def check(name, condition, detail=""):
    global tests_passed
    if condition:
        print(f"[OK] {name}")
        tests_passed += 1
    else:
        print(f"[FAIL] {name}: {detail}")
        sys.exit(1)

# Test 1: strip whitespace
r = _sanitize_comment("  hello  ")
check("strip whitespace", r == "hello", f"got {r!r}")

# Test 2: strip <script> tag + content
r = _sanitize_comment("<script>alert(1)</script>hello")
check("strip script tag+content", r == "hello", f"got {r!r}")

# Test 3: strip <b> tag, keep text
r = _sanitize_comment("<b>bold</b> text")
check("strip HTML tag, keep text", r == "bold text", f"got {r!r}")

# Test 4: strip control chars
r = _sanitize_comment("hello\x00world\x1f")
check("strip control chars", r == "helloworld", f"got {r!r}")

# Test 5: empty after clean -> None
r = _sanitize_comment("   <b></b>   ")
check("empty after clean -> None", r is None, f"got {r!r}")

# Test 6: Pydantic validator - valid comment
fb = AIFeedbackCreate(rating="like", comment="  <b>test</b>  ")
check("Pydantic validator strips HTML", fb.comment == "test", f"got {fb.comment!r}")

# Test 7: None passthrough
fb = AIFeedbackCreate(rating="like", comment=None)
check("None passthrough", fb.comment is None)

# Test 8: over limit -> ValidationError
try:
    AIFeedbackCreate(rating="like", comment="x" * 501)
    check("over limit raises error", False, "no error raised")
except Exception as e:
    check("over limit raises error", True, str(type(e).__name__))

# Test 9: whitespace-only -> None
fb = AIFeedbackCreate(rating="dislike", comment="   ")
check("whitespace-only -> None", fb.comment is None, f"got {fb.comment!r}")

# Test 10: <style> tag + content stripped
r = _sanitize_comment("<style>body{color:red}</style>normal text")
check("strip style tag+content", r == "normal text", f"got {r!r}")

print()
print(f"=== TAT CA {tests_passed} TESTS PASS ===")
