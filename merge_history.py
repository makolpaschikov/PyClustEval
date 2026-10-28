"""Copy all nine native histories into an app history directory, without overwrites."""
import argparse
from pathlib import Path
import shutil

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--into',type=Path,required=True,help='PyClustEval history directory')
args=parser.parse_args()
root=Path(__file__).resolve().parent
names=['drybean1','drybean2','drybean3','mnist1','mnist2','mnist3','synthetic1','synthetic2','synthetic3']
sources=[(name,directory) for name in names for directory in sorted((root/name/'history').glob('*'))
         if directory.is_dir() and (directory/'report.json').is_file()]
if not sources:parser.error('No exported histories found next to this script. Extract the complete results archive first.')
args.into.mkdir(parents=True,exist_ok=True)
copied=skipped=0
for series,directory in sources:
    target=args.into/(series+'_'+directory.name)
    if target.exists():
        skipped+=1
        continue
    shutil.copytree(directory,target)
    copied+=1
print(f'Copied {copied} comparisons; skipped {skipped} existing directories. No files overwritten.')
