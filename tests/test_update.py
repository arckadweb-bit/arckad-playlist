import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import update as u
from build_playlist import entry

class PlaylistTests(unittest.TestCase):
    def test_no_fuzzy_or_foreign_substitutions(self):
        rows=[{'number':1,'requested':'Rai 1 HD','aliases':[]}]
        es=[entry('Rai 1','https://example.com/it.m3u8','world',{'tvg-id':'Rai1.it'}),entry('Rai 1','https://example.com/foreign.m3u8','world',{'tvg-id':'Other.us'}),entry('Rai 2','https://example.com/2.m3u8','fulgione')]
        self.assertEqual([e['url'] for e in u.match(rows,es)[0][1]],['https://example.com/it.m3u8'])
    def test_arte_is_not_pluto_arte(self):
        rows=[{'number':37,'requested':'ARTE','international':True},{'number':273,'requested':'Pluto TV Arte'}]
        es=[entry('ARTE','https://example.com/arte.m3u8','iptvsat'),entry('Pluto TV Arte','https://jmp2.uk/plu-123.m3u8','pluto-app')]
        matches=u.match(rows,es)
        self.assertEqual(matches[0][1][0]['name'],'ARTE')
        self.assertEqual(matches[1][1][0]['name'],'Pluto TV Arte')
        self.assertEqual([len(m[1]) for m in matches],[1,1])
    def test_tokens_and_private_urls_rejected(self):
        rows=[{'number':1,'requested':'Test','aliases':[]}]
        es=[entry('Test',s,'test') for s in ['http://127.0.0.1/a','https://example.com/a?token=private','http://192.168.1.2/a']]
        self.assertEqual(u.match(rows,es)[0][1],[])
    def test_order_quality_and_deduplication(self):
        oldroot,oldreport=u.ROOT,u.REPORT
        try:
            with tempfile.TemporaryDirectory() as d:
                u.ROOT=Path(d);u.REPORT=Path(d)/'reports';u.REPORT.mkdir()
                a=entry('Uno','https://example.com/a.m3u8','test',{'tvg-id':'Uno.it'})
                b=entry('Uno HD','https://example.com/b.m3u8','test',{'tvg-id':'Uno.it'})
                c=entry('Due','https://example.com/c.m3u8','test',{'tvg-id':'Due.it'})
                matches=[({'number':1,'requested':'Uno HD'},[a,b]),({'number':2,'requested':'Assente'},[]),({'number':3,'requested':'Due HD'},[c]),({'number':4,'requested':'Uno ancora'},[b])]
                checks={e['url']:{'status':'verified','has_video':True,'height':h,'width':w,'checked_at':u.now()} for e,h,w in [(a,480,854),(b,1080,1920),(c,480,854)]}
                self.assertTrue(u.publish(matches,checks))
                text=(u.ROOT/'ARCKAD_TV.m3u').read_text()
                self.assertEqual(text.count('#EXTINF'),2)
                self.assertLess(text.index('tvg-chno="1"'),text.index('tvg-chno="3"'))
                self.assertIn('Uno HD',text);self.assertNotIn('Due HD',text)
                self.assertNotIn(a['url'],text)
                result=json.loads((u.REPORT/'channels.json').read_text())
                self.assertEqual([r['status'] for r in result],['verified','unavailable','verified','duplicate'])
                # A network-wide failure never replaces a good publication with an empty list.
                self.assertFalse(u.publish(matches,{}))
                self.assertEqual((u.ROOT/'ARCKAD_TV.m3u').read_text(),text)
        finally:u.ROOT,u.REPORT=oldroot,oldreport
    def test_rai4k_does_not_match_mislabeled_mediaset(self):
        row=next(r for r in u.load_requests() if r['requested']=='Rai 4K')
        bad=entry('Rai 4K','https://live02-seg.msf.cdn.mediaset.net/live/ch-kq/kq-clr.isml/index.m3u8','previous-publication')
        self.assertEqual(u.match([row],[bad])[0][1],[])
    def test_super_is_not_filtered_as_arte(self):
        row={'number':37,'requested':'Super!'}
        candidate=entry('Super!','https://example.com/pluto/super.m3u8','pluto-app')
        self.assertEqual(len(u.match([row],[candidate])[0][1]),1)
    def test_original_order_complete(self):
        rows=u.load_requests()
        self.assertEqual([r['number'] for r in rows],list(range(1,72)))

if __name__=='__main__':unittest.main()
