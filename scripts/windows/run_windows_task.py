import sys,os,json,dataclasses,datetime,logging
from pathlib import Path
from types import SimpleNamespace
base=Path(os.environ["OS_OMNI_WINDOWS_EXPERIMENT"]);repo=Path(__file__).resolve().parents[2];sys.path.insert(0,str(repo))
os.environ["PATH"]=r"C:\Program Files (x86)\VMware\VMware Workstation"+os.pathsep+os.environ.get("PATH","")
def main():
 from platforms.windows.runtime_config import load_windows_runtime_config
 from platforms.windows.runtime_env.vm_manager import start_windows_vm_session
 from platforms.windows.runners.episode import run_benchmark_task_command
 from platforms.windows.core.types import load_task_from_file
 input_task=load_task_from_file(repo/sys.argv[1])
 state=json.loads((base/"experiment.json").read_text(encoding="utf-8-sig"));assert state["snapshot"]=="author-windows-baseline-ready"
 validation=json.loads((base/"preflight-notepad/validation.json").read_text());assert validation["phase"]=="passed_requires_reset_before_ds"
 secrets=json.loads((Path.home()/".codex/secrets/os-omni-deepseek.json").read_text(encoding="utf-8-sig"))
 for key,value in secrets.items():os.environ[key]=value
 status={"phase":"resetting_only_new_ready_baseline","pid":os.getpid(),"task_id":input_task.id,"formal_model":"deepseek_flash","reasoning_effort":"none"}
 def save(): (base/"first-formal-status.json").write_text(json.dumps(status,indent=2),encoding="utf-8")
 save()
 cfg=dataclasses.replace(load_windows_runtime_config(),vm_provider="vmware",vm_path=state["first_boot"]["vmx"],vm_password="password",vm_snapshot_name=state["snapshot"],vm_reset_between_tasks=True,vm_stop_on_exit=False,vm_use_provider_ip=True,vm_guest_username="User",vm_guest_password="password")
 try:
  session=start_windows_vm_session(cfg)
  # Always deploy the verified host runtime after reset; the clean baseline predates this repair.
  from platforms.windows.runtime_env.vm_manager import VMwareWindowsVMProvider,VMwareWindowsGuestAgent
  from platforms.windows.runtime_env.controller import WindowsRuntimeController
  import time
  guest=VMwareWindowsGuestAgent(provider=VMwareWindowsVMProvider(vm_password=cfg.vm_password),vm_path=cfg.vm_path,username="User",password="password")
  guest.bootstrap_runtime(runtime_port=cfg.runtime_port,runtime_token=cfg.runtime_token)
  deadline=time.monotonic()+45
  while True:
   try:
    controller=WindowsRuntimeController(runtime_url="http://"+session.runtime_host+":"+str(cfg.runtime_port),token=cfg.runtime_token,timeout=5)
    probe=controller.run_python_script("print('input policy active')",timeout=10)
    assert probe.get("input_delivery_policy",{}).get("typing_interval_floor_seconds")==0.08
    break
   except Exception:
    if time.monotonic()>deadline:raise RuntimeError("Updated input delivery policy was not confirmed")
    time.sleep(2)
  os.environ["HELLOWORLD_WINDOWS_VM_PATH"]=cfg.vm_path;os.environ["HELLOWORLD_WINDOWS_VM_PASSWORD"]=cfg.vm_password;os.environ["HELLOWORLD_WINDOWS_VM_SNAPSHOT_NAME"]=cfg.vm_snapshot_name
  os.environ["HELLOWORLD_WINDOWS_VM_GUEST_USERNAME"]="User";os.environ["HELLOWORLD_WINDOWS_VM_GUEST_PASSWORD"]="password"
  attempt=int(sys.argv[2]) if len(sys.argv)>2 else 1
  out=base/"runs"/input_task.id/("attempt-%03d"%attempt);out.mkdir(parents=True,exist_ok=True);os.environ["WINDOWS_OUTPUT_DIR"]=str(out)
  logging.basicConfig(level=logging.INFO,handlers=[logging.FileHandler(out/"runner.log",encoding="utf-8")])
  class Redact(logging.Filter):
   def filter(self,record):
    msg=record.getMessage()
    for secret in [cfg.runtime_token]+list(secrets.values()):
     if secret:msg=msg.replace(secret,"[REDACTED]")
    record.msg=msg;record.args=();return True
  for handler in logging.getLogger().handlers:handler.addFilter(Redact())
  taskpath=repo/sys.argv[1];task=load_task_from_file(taskpath)
  args=SimpleNamespace(task_file=str(taskpath),goal=None,model="deepseek_flash",max_steps=min(180,task.max_steps),timeout=None,action_mode="code_adapter",observation_mode="screenshot_only",history_window=3,vm_ip=session.runtime_host,runtime_port=cfg.runtime_port,runtime_token=cfg.runtime_token,vm_guest_password="password",execution_file=None,resume_from_trajectory=None,skip_initialization=False)
  status.update(phase="ds_running",run_dir=str(out),max_steps=args.max_steps);save()
  state=json.loads((base/"experiment.json").read_text(encoding="utf-8-sig"));state["phase"]="formal_first_task";state["formal_runs_started"]=True;state["current_task"]=status["task_id"];(base/"experiment.json").write_text(json.dumps(state,indent=2),encoding="utf-8")
  code=run_benchmark_task_command(args);status.update(phase="completed_pending_gpt_audit",exit_code=code);save();print("First formal attempt completed; audit required",flush=True)
 except Exception as exc:
  status.update(phase="needs_diagnosis",error_type=type(exc).__name__);save();print("Formal worker needs diagnosis: "+type(exc).__name__,flush=True)
if __name__=="__main__":main()
