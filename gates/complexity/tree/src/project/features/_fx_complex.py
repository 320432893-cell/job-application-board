# 反向样本:控制流真缠绕(9 路嵌套 if/elif + for 内三分支 + 嵌套 while + try 双 except + 5 项 and 链),
# 推导式为零。mccabe = 18 > 阈值 15。刻意不写 noqa —— 写了就等于把要验的那道闸自己关掉。
def far_too_complex(a: int, b: int, c: int, d: int, e: int) -> int:  # noqa: PLR0911, PLR0912
    total = 0
    if a > 0:
        if b > 0:
            total += 1
        elif b < 0:
            total += 2
        else:
            total += 3
    elif a < 0:
        if c > 0:
            total += 4
        elif c < 0:
            total += 5
        else:
            total += 6
    else:
        if d > 0:
            total += 7
        elif d < 0:
            total += 8
        else:
            total += 9
    for i in range(10):
        if i % 2 == 0:
            total += i
        elif i % 3 == 0:
            total -= i
        else:
            total *= 2
        while total > 100:
            total -= 10
            if total % 7 == 0:
                break
    try:
        if e:
            total //= e
    except ZeroDivisionError:
        total = 0
    except TypeError:
        total = -1
    if a and b and c and d and e:
        total += 100
    return total
