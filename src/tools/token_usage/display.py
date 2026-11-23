"""Compact current-session metrics for the browser panel."""


def format_session_info(usage, applications):
    cost = 'unknown' if usage.cost is None else f'${usage.cost:.4f}'
    tokens = f'{usage.total:,}'
    if usage.unavailable:
        tokens += ' (partial)'
    return (f'Total scanned: {applications.scanned:,} | '
            f'Submitted: {applications.submitted:,} | '
            f'Tokens used: {tokens} | Cost: {cost}')
