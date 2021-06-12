import calc


def test_calc_addition():
    """Verify the output of `calc_addition` function"""
    output = calc.sum(2,4)
    assert output == 6


def test_calc_substraction():
    """Verify the output of `calc_substraction` function"""
    output = calc.sub(2, 4)
    assert output == -2


def test_calc_multiply():
    """Verify the output of `calc_multiply` function"""
    output = calc.mult(2,4)
    assert output == 8


def test_calc_division():
    """Verify the output of `calc_multiply` function"""
    output = calc.div(8,4)
    assert output == 2
