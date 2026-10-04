"""Summarize an MNIST evaluation JSON without inspecting design files."""
import argparse,json
from pathlib import Path
import numpy as np


def summarize(path):
    report=json.loads(Path(path).read_text());rows=report['samples'];confusion=np.zeros((10,10),dtype=int)
    failed=[];rail_violations=0
    for r in rows:
        if 'error' in r:failed.append(r['index']);continue
        confusion[r['label'],r['prediction']]+=1
        rail_violations+=any(v<0 or v>3.3 for v in r['adc'])
    return {'count':report['count'],'correct':report['correct'],'accuracy':report['accuracy'],'solver_failures':report['solver_failures'],'seconds':report['seconds'],'confusion_matrix_true_rows_predicted_columns':confusion.tolist(),'correct_per_class':confusion.diagonal().tolist(),'total_per_class':confusion.sum(axis=1).tolist(),'adc_outside_0_3v3_samples':rail_violations,'failed_indices':failed}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);a=p.parse_args();print(json.dumps(summarize(a.report),indent=2))
