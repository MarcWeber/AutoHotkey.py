from textwrap import dedent

from conftest import run_embed_python, run_from_input


def test_stdin():
    code = "import sys; print(__name__, sys.argv)"
    res = run_embed_python(["-"], input=code)
    assert res.stdout == "__main__ ['-']\n"
    assert res.returncode == 0

    res = run_embed_python(['-', 'script.py', '2', '3'], input=code)
    assert res.stdout == "__main__ ['-', 'script.py', '2', '3']\n"
    assert res.returncode == 0

    res = run_from_input("""\
        try:
            rest
        except NameError:
            pass
        else:
            print("'rest' is in scope")
        """)
    assert res.stdout == ""
    assert res.returncode == 0


def test_script(tmpdir):
    script = tmpdir / "script.py"
    script.write("import sys; print(__name__, sys.argv)")
    res = run_embed_python([str(script)])
    assert res.stdout == f"__main__ [{repr(str(script))}]\n"
    assert res.returncode == 0

    beep = tmpdir / "beep.py"
    beep.write("import sys; print(sys.argv); import boop")
    boop = tmpdir / "boop.py"
    boop.write("print('boop')")
    res = run_embed_python([str(beep)])
    assert res.stdout == f"[{repr(str(beep))}]\nboop\n", (
        "module 'beep' must be able to load the module 'boop' because they are "
        "in the same directory"
    )
    assert res.returncode == 0


def test_module(tmpdir):
    script = tmpdir / "script.py"
    script.write("import sys; print(__name__, sys.argv)")
    res = run_embed_python(["-m", "script", "ahk.py", "1", "2"], cwd=tmpdir)
    assert res.stdout == f"__main__ [{repr(str(script))}, 'ahk.py', '1', '2']\n"
    assert res.returncode == 0


def test_system_exit():
    res = run_from_input("import sys; sys.exit()")
    assert res.returncode == 0

    res = run_from_input("import sys; sys.exit(1)")
    assert res.returncode == 1

    res = run_from_input("import sys; sys.exit(2)")
    assert res.returncode == 2

    res = run_from_input("import sys; sys.exit('bye')", quiet=True)
    assert res.returncode == 1
    assert res.stderr == "bye\n"

    res = run_from_input("raise SystemExit")
    assert res.returncode == 0

    res = run_from_input("raise SystemExit(None)")
    assert res.returncode == 0

    res = run_from_input("raise SystemExit(1)")
    assert res.returncode == 1


def test_tracebacks(tmpdir):
    res = run_from_input("1/0", quiet=True)
    assert res.stderr == dedent("""\
        Traceback (most recent call last):
          File "<stdin>", line 1, in <module>
        ZeroDivisionError: division by zero
        """)
    assert res.returncode == 1

    script = tmpdir / "script.py"
    script.write("1/0")
    res = run_embed_python(["-q", str(script)])
    assert res.stderr == dedent(f"""\
        Traceback (most recent call last):
          File "{script}", line 1, in <module>
            1/0
        ZeroDivisionError: division by zero
        """)
    assert res.returncode == 1

    res = run_embed_python(["-q", "script.py"], cwd=tmpdir)
    assert res.stderr == dedent("""\
        Traceback (most recent call last):
          File "script.py", line 1, in <module>
            1/0
        ZeroDivisionError: division by zero
        """)
    assert res.returncode == 1

    res = run_from_input("import", quiet=True)
    assert res.stderr == dedent("""\
          File "<stdin>", line 1
            import
                 ^
        SyntaxError: invalid syntax
        """)
    assert res.returncode == 1

    script.write("import")
    res = run_embed_python(["-q", str(script)])
    assert res.stderr == dedent(f"""\
          File "{script}", line 1
            import
                 ^
        SyntaxError: invalid syntax
        """)
    assert res.returncode == 1

    beep = tmpdir / "beep.py"
    beep.write('import boop')
    boop = tmpdir / "boop.py"
    boop.write("import")
    res = run_embed_python(["-q", str(beep)])
    assert res.stderr == dedent(f"""\
        Traceback (most recent call last):
          File "{beep}", line 1, in <module>
            import boop
          File "{boop}", line 1
            import
                 ^
        SyntaxError: invalid syntax
        """)
    assert res.returncode == 1

    res = run_embed_python(["-q", "nonexistent.py"])
    assert res.stderr == "Can't open file: [Errno 2] No such file or directory: 'nonexistent.py'\n"
    assert res.returncode == 2

    res = run_embed_python(["-q", "-m", "nonexistent"])
    assert res.returncode == 1