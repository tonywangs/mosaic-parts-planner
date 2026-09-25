"""Bounded budget sweeps. All saved geometry is independently reconstructed."""
from copy import deepcopy
import time

from .joint_inputs import inputs, MAX_ERROR
from .joint_solver import solve
from .joint_validate import validate, validate_plan
from .model import InputError
from .packing_inputs import validate_settings

LABELS = {'optimal': 'Proven optimal', 'feasible': 'Validated feasible without proof',
          'infeasible': 'Proven infeasible', 'unknown': 'Unresolved'}
SCOPE = ('Nondominance compares returned plans only. These sampled budgets do not exhaust all '
         'trade-offs and do not prove a Pareto frontier. Piece-count ties are not optimized for error.')


def budgets_checked(budgets):
    if (not isinstance(budgets, list) or not 1 <= len(budgets) <= 12 or
            any(type(b) is not int or not 0 <= b <= MAX_ERROR for b in budgets)):
        raise InputError(f'provide 1–12 integer budgets in 0–{MAX_ERROR}')
    return list(budgets)


def fingerprint(placements):
    # IDs and list order do not change physical geometry.
    return tuple(sorted(tuple(p[k] for k in ('y', 'x', 'color_id', 'shape', 'width', 'height', 'rotation'))
                        for p in placements))


def nondominated(plans):
    def dominates(a, b):
        x, y = (a['result'][k] for k in ('image_error', 'piece_count'))
        u, v = (b['result'][k] for k in ('image_error', 'piece_count'))
        return x <= u and y <= v and (x < u or y < v)
    return [not any(dominates(q, p) for q in plans) for p in plans]


def make_plan(problem, inventory, answer, settings):
    if not isinstance(answer, dict):
        raise InputError('invalid solver answer')
    status, reason = answer.get('status'), answer.get('termination')
    if (status not in LABELS or reason not in ('exhausted', 'time_limit', 'node_limit', 'cancelled')
            or (status in ('optimal', 'infeasible')) != (reason == 'exhausted')):
        raise InputError('inconsistent solver status')
    for key in ('nodes', 'candidates_considered'):
        if type(answer.get(key)) is not int or answer[key] < 0:
            raise InputError('invalid solver counters')
    if answer['nodes'] > settings['node_limit']:
        raise InputError('solver exceeded node allowance')
    if answer.get('placements') is None:
        if status not in ('infeasible', 'unknown') or any(answer.get(k) is not None for k in ('piece_count', 'image_error')):
            raise InputError('inconsistent solver result without placements')
        return None
    checked = validate(problem, inventory, answer['placements'])
    plan = {'schema_version': 3, 'problem': deepcopy(problem), 'inventory': deepcopy(inventory),
            'placements': deepcopy(answer['placements']), 'input_grid': checked['grid'],
            'recolored_cells': checked['recolored_cells'],
            'result': {k: v for k, v in answer.items() if k != 'placements'},
            'settings': settings, 'source': None,
            'generator': {'name': 'mosaic-parts-planner', 'solver': 'joint-integer-dfs-v1'},
            'coordinates': 'front view; zero-based x right, y down; width × height'}
    validate_plan(plan, problem, inventory)
    return plan


def explore(problem, inventory, budgets, *, time_limit=10.0, node_limit=100_000,
            total_time_limit=60.0, total_node_limit=600_000, section_size=8,
            clock=time.monotonic, cancelled=lambda: False):
    budgets = budgets_checked(budgets)
    validate_settings(time_limit, node_limit, section_size)
    validate_settings(total_time_limit, total_node_limit)
    problem, inventory = inputs(problem, inventory)
    settings = dict(time_limit=time_limit, node_limit=node_limit, total_time_limit=total_time_limit,
                    total_node_limit=total_node_limit, section_size=section_size)
    start, consumed = clock(), 0
    outcomes, plans, seen, solved = [], [], {}, {}
    stopped = False
    for budget in budgets:
        if budget in solved:
            outcomes.append(deepcopy(solved[budget]))
            continue
        stopped = stopped or cancelled()
        remaining = total_time_limit - (clock() - start)
        nodes = min(node_limit, max(0, total_node_limit - consumed))
        seconds = min(time_limit, max(0, remaining))
        reason = ('cancelled' if stopped else 'total_time_limit' if remaining <= 0 else
                  'total_node_limit' if consumed >= total_node_limit else None)
        p = problem | {'error_budget': budget}
        plan = None
        if reason:
            answer = dict(status='unknown', termination=reason, piece_count=None, image_error=None,
                          nodes=0, candidates_considered=0, lower_bound=None)
        else:
            answer = solve(deepcopy(p), deepcopy(inventory), time_limit=seconds, node_limit=nodes,
                           clock=clock, cancelled=cancelled)
            plan = make_plan(p, inventory, answer, {'time_limit_seconds': seconds,
                             'node_limit': nodes, 'section_size': section_size})
            stopped = stopped or answer['termination'] == 'cancelled'
            consumed += answer['nodes']
        outcome = {'budget': budget, 'plan_id': None,
                   'result': {k: v for k, v in answer.items() if k != 'placements'}}
        if plan:
            key = fingerprint(plan['placements'])
            if key not in seen:
                seen[key] = f'plan-{len(plans)+1}'
                plans.append({'id': seen[key], 'plan': plan})
            outcome['plan_id'] = seen[key]
        solved[budget] = outcome
        outcomes.append(deepcopy(outcome))
    for entry, nd in zip(plans, nondominated([e['plan'] for e in plans])):
        entry['nondominated_among_returned'] = nd
    report = {'schema_version': 1, 'kind': 'mosaic-budget-explorer', 'scope': SCOPE,
              'problem': problem, 'inventory': inventory, 'budgets': budgets, 'settings': settings,
              'outcomes': outcomes, 'plans': plans, 'nodes_consumed': consumed}
    validate_report(report)
    return report


def validate_report(report):
    """Validate untrusted saved data without optimizing; proofs remain solver claims."""
    if (not isinstance(report, dict) or type(report.get('schema_version')) is not int or
            report['schema_version'] != 1 or report.get('kind') != 'mosaic-budget-explorer'):
        raise InputError('expected budget explorer schema version 1')
    try:
        p, inv = inputs(report['problem'], report['inventory'])
        budgets = budgets_checked(report['budgets'])
        settings = report['settings']
        validate_settings(settings['time_limit'], settings['node_limit'], settings['section_size'])
        validate_settings(settings['total_time_limit'], settings['total_node_limit'])
        entries, outcomes = report['plans'], report['outcomes']
        if not isinstance(entries, list) or len(entries) > 12 or not isinstance(outcomes, list) or len(outcomes) != len(budgets):
            raise InputError('invalid plan/outcome counts')
        by_id, keys = {}, set()
        for i, entry in enumerate(entries, 1):
            if entry['id'] != f'plan-{i}':
                raise InputError('invalid plan ID')
            plan = entry['plan']
            q = p | {'error_budget': plan['problem']['error_budget']}
            validate_plan(plan, q, inv)
            validate_settings(plan['settings']['time_limit_seconds'], plan['settings']['node_limit'],
                              plan['settings']['section_size'])
            key = fingerprint(plan['placements'])
            if key in keys:
                raise InputError('duplicate plan geometry')
            keys.add(key)
            by_id[entry['id']] = plan
        used, unique = set(), {}
        for budget, outcome in zip(budgets, outcomes):
            if type(outcome['budget']) is not int or outcome['budget'] != budget:
                raise InputError('budget/outcome mismatch')
            r = outcome['result']
            plan_id = outcome['plan_id']
            if plan_id is not None:
                if plan_id not in by_id:
                    raise InputError('unknown plan ID')
                plan = by_id[plan_id]
                make_plan(p | {'error_budget': budget}, inv, r | {'placements': plan['placements']},
                          {'time_limit_seconds': settings['time_limit'], 'node_limit': settings['node_limit'],
                           'section_size': settings['section_size']})
                used.add(plan_id)
            elif r.get('termination') in ('total_time_limit', 'total_node_limit'):
                if (r.get('status') != 'unknown' or r.get('piece_count') is not None or
                        r.get('image_error') is not None or r.get('nodes') != 0 or r.get('candidates_considered') != 0):
                    raise InputError('invalid unstarted outcome')
            else:
                make_plan(p | {'error_budget': budget}, inv, r | {'placements': None},
                          {'node_limit': settings['node_limit']})
            if budget in unique and unique[budget] != outcome:
                raise InputError('repeated budgets disagree')
            unique[budget] = outcome
        for plan_id, plan in by_id.items():
            if not any(o['plan_id'] == plan_id and o['budget'] == plan['problem']['error_budget']
                       and o['result'] == plan['result'] for o in outcomes):
                raise InputError('saved plan proof metadata lacks a matching budget outcome')
        if used != set(by_id):
            raise InputError('unreferenced plan')
        for entry, nd in zip(entries, nondominated(list(by_id.values()))):
            if type(entry['nondominated_among_returned']) is not bool or entry['nondominated_among_returned'] != nd:
                raise InputError('incorrect nondominance flag')
        total = sum(o['result']['nodes'] for o in unique.values())
        if type(report['nodes_consumed']) is not int or total != report['nodes_consumed'] or total > settings['total_node_limit']:
            raise InputError('invalid total node count')
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise InputError(f'malformed explorer report: {exc}') from exc
    return report


def selected_plan(report, plan_id):
    validate_report(report)
    for entry in report['plans']:
        if entry['id'] == plan_id:
            return deepcopy(entry['plan'])
    raise InputError('selected plan ID does not exist')
