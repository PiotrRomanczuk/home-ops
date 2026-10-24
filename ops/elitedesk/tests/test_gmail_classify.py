"""Unit tests for gmail_classify: rule precedence, own mail, people, tab fallbacks, full coverage."""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gmail_inventory  # noqa: E402
from gmail_report import report  # noqa: E402
from gmail_classify import EXAMPLE_RULES, FALLBACK, Rule, classify, classify_all, is_protected, load_rules, subcategory  # noqa: E402

CFG = load_rules(Path(__file__).resolve().parent / 'fixtures' / 'gmail_rules.test.json')
ME = 'p.romanczuk@gmail.com'


def row(addr, subject='', labels='', to=ME, unsub=0):
    return {'from_addr': addr, 'subject': subject, 'labels': labels, 'to_addrs': to, 'has_unsub': unsub}


class ClassifyTest(unittest.TestCase):
    def label(self, r, people=frozenset()):
        return classify(r, CFG, set(people))[0]

    def test_domain_rule_matches_subdomains(self):
        self.assertEqual(self.label(row('promo@news.cooperpress.com')), 'Newslettery/Dev')
        self.assertEqual(self.label(row('x@notcooperpress.com', labels='CATEGORY_UPDATES')), 'Powiadomienia')

    def test_first_rule_wins_strummy_before_github_subject(self):
        self.assertEqual(self.label(row(ME, 'Daily Notification Summary – 10/20/2026', to=ME)),
                         'Gitara/Strummy-system')

    def test_invoice_subject_beats_vendor_category(self):
        self.assertEqual(self.label(row('billing@vercel.com', 'Your invoice for October')), 'Finanse/Faktury')
        self.assertEqual(self.label(row('notifications@vercel.com', 'Deployment failed')), 'Dev/Vercel')

    def test_sender_plus_subject_rule_requires_both(self):
        self.assertEqual(self.label(row('messages-noreply@linkedin.com', 'Zaproszenie na rozmowę')), 'Praca/Rekrutacja')
        self.assertNotEqual(self.label(row('messages-noreply@linkedin.com', 'New connection')), 'Praca/Rekrutacja')

    def test_own_mail_uses_recipient(self):
        self.assertEqual(self.label(row(ME, 'Re: sprawa', to='biuro@kancelaria-example.pl')), 'Prawne')
        self.assertEqual(self.label(row(ME, 'hej', to='kolega@firma.pl')), 'Ludzie/Wysłane')
        self.assertEqual(self.label(row(ME, 'notatka', to=ME)), 'Inne/Do-siebie')

    def test_job_boards(self):
        self.assertEqual(self.label(row('jobs-noreply@linkedin.com', 'x')), 'Praca/Szukanie-pracy')
        self.assertEqual(self.label(row('mailer-daemon@googlemail.com', 'Delivery Status Notification (Failure)')), 'Dev/Zwroty-poczty')
        self.assertEqual(self.label(row('noreply@gmail.com')), 'Inne/Do-przejrzenia')  # automated never Ludzie

    def test_people(self):
        self.assertEqual(self.label(row('ania@firma.pl'), people={'ania@firma.pl'}), 'Ludzie')
        self.assertEqual(self.label(row('ktos@wp.pl')), 'Ludzie')
        self.assertEqual(self.label(row('promo@wp.pl', unsub=1, labels='CATEGORY_PROMOTIONS')), 'Promocje')

    def test_tab_fallbacks(self):
        self.assertEqual(self.label(row('a@shop.pl', labels='CATEGORY_PROMOTIONS')), 'Promocje')
        self.assertEqual(self.label(row('a@site.pl', labels='CATEGORY_SOCIAL')), 'Społecznościowe')
        self.assertEqual(self.label(row('a@list.pl', unsub=1, labels='CATEGORY_UPDATES')), 'Newslettery')
        self.assertEqual(self.label(row('a@bot.pl', labels='CATEGORY_UPDATES')), 'Powiadomienia')
        self.assertEqual(self.label(row('a@bot.pl', labels='INBOX')), FALLBACK)


class ProtectTest(unittest.TestCase):
    CFG = {**CFG, 'protect_labels': ('Praca', 'Ludzie'),
           'protect_subject': __import__('re').compile(r'(payslip|umow[ay])', __import__('re').I)}

    def test_protected(self):
        self.assertTrue(is_protected('Praca/Zatrudnienie', 'x', '', self.CFG))
        self.assertTrue(is_protected('Promocje', 'Payslip Week 22', '', self.CFG))
        self.assertTrue(is_protected('Promocje', 'x', 'INBOX,STARRED', self.CFG))
        self.assertFalse(is_protected('Promocje', '-50% na wszystko', 'INBOX', self.CFG))
        self.assertFalse(is_protected('Pracownia', 'x', '', self.CFG))  # prefix must be a whole segment


class SubcategoryTest(unittest.TestCase):
    CFG = {**CFG, 'subrules': [('Dev/GitHub', Rule('Dev/GitHub/CI', subject=__import__('re').compile('run failed', 2)))]}

    def test_child_label_added_alongside_parent(self):
        self.assertEqual(subcategory('Dev/GitHub', row('n@github.com', 'Run failed: E2E'), self.CFG), 'Dev/GitHub/CI')
        self.assertIsNone(subcategory('Dev/GitHub', row('n@github.com', 'PR merged'), self.CFG))
        self.assertEqual(subcategory('Ludzie', row('ania@wp.pl'), self.CFG), 'Ludzie/Znajomi')
        self.assertEqual(subcategory('Ludzie', row('jan@firma.pl'), self.CFG), 'Ludzie/Firmy')
        self.assertIsNone(subcategory('Ludzie', row('ania@wp.pl'), CFG))  # no subrules configured → flat


class ExampleRulesTest(unittest.TestCase):
    def test_committed_example_parses(self):
        cfg = load_rules(EXAMPLE_RULES)
        self.assertTrue(cfg['rules'])
        self.assertEqual(classify(row('x@github.com'), cfg, set())[0], 'Dev/GitHub')


class CoverageTest(unittest.TestCase):
    def test_every_row_gets_exactly_one_label(self):
        db = sqlite3.connect(':memory:')
        db.executescript(gmail_inventory.SCHEMA)
        rows = [('1', 'notifications@github.com', '', 'INBOX', ME, 0),
                ('2', ME, 'hej', 'SENT', 'ania@firma.pl', 0),
                ('3', 'ania@firma.pl', 'odp', 'INBOX', ME, 0),
                ('4', 'x@unknown.io', '', '', ME, 0)]
        db.executemany('INSERT INTO messages (id, from_addr, subject, labels, to_addrs, has_unsub) '
                       'VALUES (?,?,?,?,?,?)', rows)
        out = classify_all(db, CFG)
        ids = sorted(i for v in out.values() for i in v)
        self.assertEqual(ids, ['1', '2', '3', '4'])
        self.assertIn('3', out['Ludzie'])  # learned from Piotr's sent mail
        self.assertIn('| Dev/GitHub | 1 |', report(db, CFG))


if __name__ == '__main__':
    unittest.main()
