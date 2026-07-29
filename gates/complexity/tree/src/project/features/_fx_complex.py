def far_too_complex(a: int, b: int, c: int) -> int:  # noqa: C901, PLR0911, PLR0912
    total = 0
    if a and b:
        total += 1
    if a and c:
        total += 2
    if b and c:
        total += 3
    if a or b:
        total += 4
    if a or c:
        total += 5
    if b or c:
        total += 6
    if a and b and c:
        total += 7
    if a or b or c:
        total += 8
    if a and not b:
        total += 9
    if b and not c:
        total += 10
    if c and not a:
        total += 11
    return total
