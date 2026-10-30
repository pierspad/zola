import copy
import unittest
from compare_matrix import compare, METHOD


def fixture():
    sample={'rss_method':METHOD,'exact_output_equal':True,'seconds':1,'cpu_total_seconds':2,'peak_rss_bytes':100*2**20}
    stats={'median_seconds':1,'median_cpu_seconds':2,'max_peak_rss_bytes':100*2**20,'mad_seconds':.01}
    return {'fixture_version':1,'compatibility_policy':'common-search-v2','platform':'linux','cpu_model':'test','binary_sha256':'a','fork_build':{'binary_sha256':'a','toolchain':'rustc','features':'default','profile':'release'},'parameters':{'threads':4,'warmups':2,'feed_limit':50},'upstream':{'binary_sha256':'up-a'},'cases':[{'articles':100,'languages':1,'profile':'stress','status':'passed','fixture_sha256':'fixture','samples':{k:[copy.deepcopy(sample)] for k in ('full','incremental')},'summary':{k:copy.deepcopy(stats) for k in ('full','incremental')}}]}


class PreviousReleaseTests(unittest.TestCase):
    def test_binary_change_allowed_and_official_change_explicit(self):
        old=fixture();new=copy.deepcopy(old);new['binary_sha256']='b';new['fork_build']['binary_sha256']='b';new['upstream']['binary_sha256']='up-b'
        result=compare(new,old)
        self.assertEqual(result['status'],'compatible_no_regression_flag');self.assertTrue(result['fork_binary_changed']);self.assertTrue(result['official_baseline_changed'])

    def test_material_resource_regressions(self):
        old=fixture();new=copy.deepcopy(old)
        for mode in ('full','incremental'):
            for key in ('median_seconds','median_cpu_seconds','max_peak_rss_bytes'):new['cases'][0]['summary'][mode][key]*=2
        result=compare(new,old)
        self.assertEqual(result['status'],'regression');self.assertEqual(sum(r.get('regression',False) for r in result['comparisons']),6)

    def test_noise_and_absolute_floor(self):
        old=fixture();new=copy.deepcopy(old);new['cases'][0]['summary']['full']['median_seconds']=1.16;new['cases'][0]['summary']['full']['mad_seconds']=.1
        self.assertEqual(compare(new,old)['status'],'inconclusive_noise')

    def test_incompatible_fixture_method_and_missing_metrics(self):
        for change in ('fixture','method','metrics','compiler'):
            with self.subTest(change=change):
                old=fixture();new=copy.deepcopy(old)
                if change=='fixture':new['cases'][0]['fixture_sha256']='changed'
                if change=='method':new['cases'][0]['samples']['full'][0]['rss_method']='direct wait4'
                if change=='metrics':del new['cases'][0]['summary']['full']['median_cpu_seconds']
                if change=='compiler':new['fork_build']['toolchain']='other'
                self.assertEqual(compare(new,old)['status'],'incompatible')

    def test_no_matched_cases_is_incompatible(self):
        old=fixture();new=copy.deepcopy(old);new['cases'][0]['articles']=200
        self.assertEqual(compare(new,old)['status'],'incompatible')


if __name__=='__main__':unittest.main()
