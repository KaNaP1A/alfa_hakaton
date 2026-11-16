"""Create an isolated fixed-weight CatBoost blend, without fitting or installation."""
import argparse
import json
from pathlib import Path
from catboost import CatBoostRanker, sum_models
from alfa_reco.bundle import atomic_json, sha256


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--weight',type=float,default=.5,help='Weight of new candidate in [0,1]')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if not 0<=a.weight<=1: raise ValueError('Invalid blend weight')
    a.output.mkdir(parents=True,exist_ok=False)
    models=[]
    for path in (a.baseline,a.candidate):
        model=CatBoostRanker();model.load_model(str(path));models.append(model)
    if models[0].feature_names_ != models[1].feature_names_: raise ValueError('Feature schema mismatch')
    blend=sum_models(models,weights=[1-a.weight,a.weight])
    blend.save_model(str(a.output/'ranker.cbm'))
    atomic_json(a.output/'manifest.json',{'baseline_sha256':sha256(a.baseline),'candidate_sha256':sha256(a.candidate),'candidate_weight':a.weight,'ranker_sha256':sha256(a.output/'ranker.cbm'),'notice':'Experimental raw-score combination; score scale may differ. No fitting, calibration or installation.'})
    print(json.dumps({'output':str(a.output),'weight':a.weight}))

if __name__=='__main__':main()
