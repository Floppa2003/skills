"""Check the editable archival request template without third-party dependencies."""
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'assets' / 'cano-vital-record-request.template.docx'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

class CanoTemplateTests(unittest.TestCase):
    def test_sections_and_filling(self):
        with ZipFile(TEMPLATE) as archive:
            document = ET.fromstring(archive.read('word/document.xml'))
            self.assertNotIn('word/comments.xml', archive.namelist())
            self.assertNotIn('word/people.xml', archive.namelist())
            core = archive.read('docProps/core.xml').decode()
        paragraphs = [''.join(node.text or '' for node in p.iter(W + 't')) for p in document.iter(W + 'p')]
        text = '\n'.join(paragraphs)
        required = ['ФИО или организация:', 'Ваш e-mail:', 'Вид акта', 'ФИО лица,', 'Место совершения акта:', 'Дата совершения акта:', 'Вероисповедание:', 'Наименование церкви:', 'Орган, зарегистрировавший акт:', 'Дата, номер регистрации акта:', 'Текст запроса:', 'Прошлые обращения:', 'Результат услуги прошу предоставить']
        positions = [text.index(item) for item in required]
        self.assertEqual(positions, sorted(positions))
        methods = [p for p in paragraphs if p.startswith('в виде ') and 'документа' in p]
        self.assertEqual(len(methods), 4)
        self.assertTrue(any('Портала госуслуг' in p for p in methods))
        for placeholder in ('[вид акта]', '[ФИО лица]', '[место события]', '[дата или диапазон]', '[вероисповедание]', '[наименование церкви]'):
            self.assertIn(placeholder, text)
        values = {'[вид акта]': 'рождение', '[ФИО лица]': 'Иванов Иван Иванович', '[место события]': 'село Примерное', '[дата или диапазон]': '1900–1902', '[вероисповедание]': 'православие', '[наименование церкви]': 'церковь села Примерного'}
        for node in document.iter(W + 't'):
            if node.text in values:
                node.text = values[node.text]
        filled = '\n'.join(''.join(node.text or '' for node in p.iter(W + 't')) for p in document.iter(W + 'p'))
        self.assertTrue(all(value in filled for value in values.values()))
        self.assertTrue(all(key not in filled for key in values))
        self.assertTrue(all(method in filled for method in methods))
        self.assertIn('обработку моих персональных данных', text)
        self.assertIn('<dc:creator></dc:creator>', core)
        self.assertIn('<cp:lastModifiedBy></cp:lastModifiedBy>', core)

if __name__ == '__main__':
    unittest.main()
