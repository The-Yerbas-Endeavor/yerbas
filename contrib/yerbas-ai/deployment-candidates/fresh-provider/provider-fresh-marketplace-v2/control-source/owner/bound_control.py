"""Owner-authorized assignment binding and fences; no arbitrary executor inputs."""
import json,re,socket
ID=re.compile('[a-f0-9]{32}')

def dispatch(agent,method,params,rid,exchange,error):
    def reject():raise error('invalid_params')
    if method=='provider.submit_work':
        if set(params)!={'run_id','contribution','assignment_id','provider','terms_sha256'}:reject()
        if (not isinstance(params['run_id'],str) or not ID.fullmatch(params['run_id'])
            or params['assignment_id']!=params['run_id'] or params['contribution']!='text-'+params['run_id']
            or params['provider']!=socket.gethostname() or not isinstance(params['terms_sha256'],str)
            or not re.fullmatch('[a-f0-9]{64}',params['terms_sha256'])):reject()
        if not agent.submission_enabled():raise error('submission_disabled')
        target='submit_rental'
    elif method=='provider.fence_work':
        if set(params)!={'run_id'} or not isinstance(params['run_id'],str) or not ID.fullmatch(params['run_id']):reject()
        target='fence'
    elif method=='provider.work_shutdown':
        if set(params)!={'assignment_id'} or not isinstance(params['assignment_id'],str) or not ID.fullmatch(params['assignment_id']):reject()
        return exchange('shutdown_evidence',params,rid)
    else:reject()
    fingerprint=json.dumps([method,params],sort_keys=True)
    row=agent.db.execute('SELECT fingerprint,response FROM requests WHERE id=?',(rid,)).fetchone()
    if row:
        if row[0]!=fingerprint:raise error('request_id_conflict')
        if row[1]:return json.loads(row[1])
    else:
        if agent.db.execute('SELECT count(*) FROM requests').fetchone()[0]>=10000:raise error('journal_full')
        agent.db.execute('INSERT INTO requests VALUES(?,?,NULL)',(rid,fingerprint));agent.db.commit()
    # Same broker request ID reconciles a lost reply. Never generate a new ID here.
    result=exchange(target,params,rid)
    agent.db.execute('UPDATE requests SET response=? WHERE id=?',(json.dumps(result),rid));agent.db.commit()
    return result
