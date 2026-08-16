import unittest

from v11 import v13_rich_run_residual as rich
from v11 import v13_rich_run_shadow as shadow


class RichRunResidualTests(unittest.TestCase):
    def modules(self):
        return {
            name:{"status":"ACTIVE","coverage":1.0,"home_factor":1.03,"away_factor":.98}
            for name in rich.MODULES
        }

    def test_feature_vector_excludes_market(self):
        x=rich._vector(4.8,"home",self.modules())
        self.assertEqual(len(x),3+len(rich.MODULES))
        self.assertEqual(x[0],1.0); self.assertEqual(x[1],0.0)

    def test_adjustment_is_bounded(self):
        model={"coefficients":[5.0]*(3+len(rich.MODULES))}
        h,delta=rich._apply(4.5,"home",self.modules(),model)
        self.assertLessEqual(abs(delta),rich.MAX_ADJ)
        self.assertAlmostEqual(h,4.5+delta)

    def test_shadow_never_changes_production_fields(self):
        result={"phase":"FINAL","projected_home_runs":4.8,"projected_away_runs":4.2,
                "ctx":{"home":"Home","away":"Away"},"shadow_v124":{"modules":self.modules()},
                "options":[{"market":"ML","name":"Home","p_baseball_raw":.55},{"market":"ML","name":"Away","p_baseball_raw":.45}]}
        before=[dict(x) for x in result["options"]]
        artifact={"schema":rich.SCHEMA,"shadow_enabled":True,"status":"HISTORICALLY_VALIDATED_SHADOW","model":{"coefficients":[0.01]*(3+len(rich.MODULES))}}
        shadow.attach(result,artifact)
        self.assertEqual(result["options"],before)
        self.assertFalse(result["shadow_v13_rich_runs"]["affects_v13_probability"])
        self.assertEqual(result["shadow_v13_rich_runs"]["status"],"ACTIVE_SHADOW")

    def test_non_final_is_not_applied(self):
        r={"phase":"LATE","shadow_v124":{"modules":self.modules()}}
        artifact={"schema":rich.SCHEMA,"shadow_enabled":True,"model":{}}
        shadow.attach(r,artifact)
        self.assertEqual(r["shadow_v13_rich_runs"]["status"],"FINAL_ONLY")


if __name__ == "__main__": unittest.main()
