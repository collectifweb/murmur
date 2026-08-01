import time
import unittest

from aparte.hallucinations import strip


class SignedPhraseTest(unittest.TestCase):
    """Les génériques signés partent, où qu'ils soient."""

    def test_the_amara_credit_at_the_end_of_a_dictation(self):
        """Le cas réel, relevé le 22/07 dans l'historique : Whisper colle le
        générique après la dernière phrase, sur le silence de fin."""
        dictated = (
            "C’est vraiment hallucinant, ça écrit vraiment en même temps. "
            "Sous-titres réalisés par la communauté d’Amara.org"
        )
        self.assertEqual(strip(dictated), "C’est vraiment hallucinant, ça écrit vraiment en même temps.")

    def test_a_straight_apostrophe_is_recognised_too(self):
        """Whisper rend l'apostrophe droite ; polish.py ne l'a pas encore courbée."""
        self.assertEqual(strip("Bonjour. Sous-titres réalisés par la communauté d'Amara.org"), "Bonjour.")

    def test_the_credit_alone_leaves_nothing(self):
        """Une dictée entièrement silencieuse : il ne doit rien rester."""
        self.assertEqual(strip("Sous-titres réalisés par la communauté d'Amara.org"), "")

    def test_the_para_typo_variant(self):
        self.assertEqual(strip("Sous-titres réalisés para la communauté d'Amara.org"), "")

    def test_radio_canada(self):
        self.assertEqual(strip("Merci beaucoup. Sous-titrage Société Radio-Canada"), "Merci beaucoup.")

    def test_the_soustitreur_credit_with_its_heart(self):
        self.assertEqual(strip("Voilà. ❤️ par SousTitreur.com"), "Voilà.")

    def test_the_english_credit(self):
        self.assertEqual(strip("Hello there. Subtitles by the Amara.org community"), "Hello there.")

    def test_a_credit_in_the_middle_of_a_long_dictation(self):
        """Un blanc au milieu produit le générique au milieu."""
        got = strip("Premier point. Sous-titres réalisés par la communauté d'Amara.org Deuxième point.")
        self.assertEqual(got, "Premier point. Deuxième point.")

    def test_the_credit_repeated(self):
        text = (
            "Bonjour. Sous-titres réalisés par la communauté d'Amara.org "
            "Sous-titres réalisés par la communauté d'Amara.org"
        )
        self.assertEqual(strip(text), "Bonjour.")


class GenericOutroTest(unittest.TestCase):
    """Une formule de fin de vidéo ne part que si elle est tout le texte : elle
    est dictable, contrairement aux phrases signées."""

    def test_alone_it_goes(self):
        self.assertEqual(strip("Merci d'avoir regardé cette vidéo !"), "")

    def test_inside_a_real_dictation_it_stays(self):
        """Quelqu'un qui écrit le texte d'une vidéo dicte vraiment ça."""
        dictated = "Merci d'avoir regardé cette vidéo, on se retrouve la semaine prochaine."
        self.assertEqual(strip(dictated), dictated)

    def test_thanks_for_watching_alone(self):
        self.assertEqual(strip("Thanks for watching!"), "")


class RepeatedOutroTest(unittest.TestCase):
    """Sur du silence, Whisper ne rend pas l'hallucination une fois : il la
    répète et en tronque les variantes. Exiger qu'un seul motif couvre tout le
    texte laissait donc passer le cas le plus courant."""

    def test_the_pair_that_reached_a_real_history(self):
        """Vu le 01/08 : 144 s captées sur un micro qui n'entendait presque rien
        — crête à 4566 sur 32768 — et ceci livré à l'utilisateur."""
        got = strip("Merci d'avoir regardé cette vidéo. Merci d'avoir regardé.")
        self.assertEqual(got, "")

    def test_the_same_formula_twice(self):
        text = "Merci d'avoir regardé cette vidéo. Merci d'avoir regardé cette vidéo."
        self.assertEqual(strip(text), "")

    def test_variants_mixed_together(self):
        self.assertEqual(strip("Abonnez-vous. Thanks for watching. Merci d'avoir regardé."), "")

    def test_a_dictation_that_opens_with_a_formula_still_stays(self):
        """La sécurité tient à la consommation *entière* : dès qu'un mot dicté
        reste, rien ne part. C'est le cas qui distingue ce filtre d'un rasoir."""
        dictated = "Merci d'avoir regardé cette vidéo, elle explique tout le processus."
        self.assertEqual(strip(dictated), dictated)

    def test_a_long_repetition_does_not_blow_up(self):
        """Les formules partagent leurs débuts. Un motif `(?:a|b|c)+` par-dessus
        ces alternatives ambiguës part en retours arrière exponentiels dès
        quelques dizaines de répétitions — d'où la consommation pas à pas."""
        start = time.perf_counter()
        text = "Merci d'avoir regardé cette vidéo. " * 400 + "et là je dicte vraiment"
        self.assertEqual(strip(text), text.strip())
        self.assertLess(time.perf_counter() - start, 2.0)


class NoRegressionTest(unittest.TestCase):
    """Le vrai risque d'un filtre : manger une dictée légitime."""

    def test_an_ordinary_dictation_comes_out_byte_for_byte(self):
        dictated = (
            "Bonjour Sarah, merci pour l’envoi. Est-ce que ça te va si on se voit "
            "mardi à 14 h 30 ? J’ai relu le devis, tout me semble juste."
        )
        self.assertEqual(strip(dictated), dictated)

    def test_a_dictation_that_merely_mentions_amara(self):
        """« Amara.org » seul n'est pas dans la liste, et c'est voulu."""
        dictated = "Le fichier de sous-titres vient d’Amara.org, je te l’envoie."
        self.assertEqual(strip(dictated), dictated)

    def test_a_dictation_about_subtitling(self):
        dictated = "Il faudrait revoir le sous-titrage de la vidéo avant jeudi."
        self.assertEqual(strip(dictated), dictated)

    def test_line_breaks_survive(self):
        """Une liste dictée garde ses retours à la ligne : le nettoyage
        d'espaces ne touche qu'aux espaces et tabulations."""
        dictated = "Premier point\nDeuxième point\nTroisième point"
        self.assertEqual(strip(dictated), dictated)

    def test_an_empty_transcript_stays_empty(self):
        self.assertEqual(strip(""), "")


if __name__ == "__main__":
    unittest.main()
