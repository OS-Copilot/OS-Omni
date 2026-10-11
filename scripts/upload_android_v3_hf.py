import hashlib,json,os,time,traceback
from pathlib import Path
from huggingface_hub import HfApi
BASE=Path(__file__).resolve().parents[2]
STAGE=BASE/'hf-android-v3'
STATE=STAGE/'hf-upload-status.json'
def save(data):
    data.update(pid=os.getpid(),updated_at=time.time());STATE.write_text(json.dumps(data,indent=2),encoding='utf-8');print(data['phase'],flush=True)
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def main():
    data=json.loads(STATE.read_text())
    token=json.loads((Path.home()/'.codex/secrets/os-omni-huggingface.json').read_text())['HF_TOKEN']
    api=HfApi(token=token)
    data['phase']='waiting_for_verified_build';save(data)
    while True:
        build=json.loads((STAGE/'build-status.json').read_text())
        if build['phase']=='failed':raise RuntimeError('Build failed: '+build['error'])
        if build['phase']=='ready_to_upload':break
        time.sleep(15)
    folder=STAGE/'android_V3'
    manifest=json.loads((folder/'manifest.json').read_text())
    assert digest(folder/'android_V3.zip')==manifest['sha256']
    # The credential stays outside both the upload folder and image.
    data.update(phase='uploading',manifest=manifest);save(data)
    commit=api.upload_folder(repo_id=data['repo'],repo_type='dataset',revision=data['revision'],folder_path=folder,path_in_repo='android_V3',commit_message='Upload validated author-rebuilt Android V3 image and provenance')
    data.update(phase='verifying_remote',commit=str(commit.oid));save(data)
    paths=api.get_paths_info(data['repo'],paths=['android_V3/android_V3.zip'],repo_type='dataset',revision=data['revision'])
    info=paths[0]
    assert info.size==manifest['size']
    assert info.lfs and info.lfs.sha256==manifest['sha256']
    for name in ['manifest.json','validation.json','README.md']:
        from huggingface_hub import hf_hub_download
        remote=Path(hf_hub_download(repo_id=data['repo'],repo_type='dataset',revision=data['revision'],filename='android_V3/'+name,token=token))
        assert digest(remote)==digest(folder/name)
    data.update(phase='complete_remote_verified',remote_sha256=info.lfs.sha256);save(data)
if __name__=='__main__':
    try:main()
    except Exception as e:
        data=json.loads(STATE.read_text());data.update(phase='failed',error=str(e));save(data);traceback.print_exc();raise
