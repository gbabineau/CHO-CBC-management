import subprocess

from cho_cbc_management import main


def test_main(capsys):
    main()
    assert capsys.readouterr().out == "Hello from cho-cbc-management!\n"


def test_installed_command():
    result = subprocess.run(
        ["cho-cbc-management"], capture_output=True, text=True, check=True
    )
    assert result.stdout == "Hello from cho-cbc-management!\n"
