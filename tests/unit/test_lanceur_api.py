from agent_tag.api import __main__ as lanceur


def test_lanceur_refuse_une_adresse_non_locale(capsys):
    assert lanceur.main(["--hote", "0.0.0.0"]) == 2
    assert "127.0.0.1" in capsys.readouterr().err
