"""Run a fixed synthetic commercial policy on fresh simulated sessions."""
import argparse
import json
from pathlib import Path

from catboost import CatBoostClassifier
from train_commercial_simulation import evaluate, make_sessions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('artifacts/commercial_simulation_v4'))
    output = parser.parse_args().output
    courses = json.loads(Path('experiments/alfa_public_courses.json').read_text())['courses']
    model = CatBoostClassifier()
    model.load_model(str(output / 'synthetic_purchase_model.cbm'))
    report = {'synthetic_only': True,
              'note': 'Fresh seeds after fixing policy; simulated sessions only, no real purchases.',
              'sessions_each': 5000,
              'test_base': evaluate(make_sessions(courses, 5000, 23003, 'base'), model),
              'test_stress': evaluate(make_sessions(courses, 5000, 23004, 'stress'), model)}
    (output / 'confirmation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
