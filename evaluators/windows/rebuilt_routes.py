import json
from core.evaluation import BaseEvaluator,EvalResult,EvalStatus
class RebuiltRoutesEvaluator(BaseEvaluator):
 def evaluate(self,context):
  expected=context['params']['routes'];path=r'C:\Users\User\Documents\author_routes_v1\state.json'
  try:actual=json.loads(context['controller'].get_file(path))['routes']
  except Exception:actual=[]
  observation=context['controller'].observe(include_ui_tree=False)
  foreground=str(observation.foreground_app).lower()
  window=str(observation.foreground_window)
  visible=foreground in {'msedge.exe','chrome.exe','firefox.exe'} and 'Author Route Planner' in window
  passed=actual==expected and visible
  return EvalResult(status=EvalStatus.PASS if passed else EvalStatus.FAIL,message='Exact route history and final planner passed' if passed else 'Exact ordered routes or final planner differ',metadata={'version':'author-routes-v1','read_only':True,'expected':expected,'actual':actual,'check_final_route_included':True,'final_planner_visible':visible,'foreground_app':foreground,'foreground_window':window})
