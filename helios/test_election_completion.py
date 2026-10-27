import datetime
import json
import uuid
from unittest.mock import Mock, patch
from django.core.exceptions import PermissionDenied
from django.test import TestCase, RequestFactory, Client, override_settings
from helios import models, views, datatypes
from helios.workflows import homomorphic
from helios.crypto.utils import hash_b64
from helios.election_completion import process_next_completion, recovery_schedule
from helios.runtime_health import verification_state
from helios_auth.models import User


@override_settings(ALU_AUTOMATIC_COMPLETION=True,
    ALU_BRIDGE_CLIENT_ID='alu-helios-demo', ALU_BRIDGE_APP_ORIGIN='https://alu.example',
    ALU_BRIDGE_SECRET='completion-test-secret-with-thirty-two-bytes',
    RECOVERY_SECRET='completion-recovery-test-secret', ALU_BRIDGE_ELECTIONS=())
class ElectionCompletionTests(TestCase):
    def setUp(self):
        self.owner=User.objects.create(user_type='alu',user_id='owner',name='Owner',info={})
        self.e=models.Election.objects.create(uuid=str(uuid.uuid4()),short_name=str(uuid.uuid4()),
            name='Automatic archive test',admin=self.owner,openreg=True)
        models.AluElectionBinding.objects.create(uuid=self.e.uuid,election=self.e,client_id='alu-helios-demo')
        self.e.questions=[{'answer_urls':[None,None],'answers':['Alice','Bob'],'choice_type':'approval',
            'max':1,'min':0,'question':'President','short_name':'President',
            'result_type':'absolute','tally_type':'homomorphic'}]
        self.e.generate_trustee(views.ELGAMAL_PARAMS)
        self.e.save();self.e.freeze()
        self.e.voting_starts_at=datetime.datetime.utcnow()-datetime.timedelta(hours=2)
        self.e.voting_ends_at=datetime.datetime.utcnow()-datetime.timedelta(minutes=1)
        self.e.save()
        self.sent=[]
        def post(url,**kwargs):
            self.sent.append((url,kwargs['json']))
            return Mock(status_code=200,json=lambda:{'saved':True})
        self.post=patch('helios.election_completion.requests.post',side_effect=post).start()
        self.addCleanup(patch.stopall)
        patch('helios.bridge_eligibility.statuses',side_effect=lambda election,vs:{v['subject']:{'student':True,'committee':False,'events':[]} for v in vs}).start()

    def status(self):
        r=RequestFactory().get('/internal/verification-state',HTTP_AUTHORIZATION='Bearer completion-recovery-test-secret')
        return json.loads(verification_state(r).content)

    def vote(self,verified=True):
        user=User.objects.create(user_type='alu',user_id='student',info={'email':'student@alustudent.com','email_verified':True})
        voter=models.Voter.objects.create(election=self.e,user=user,uuid=str(uuid.uuid4()))
        encrypted=homomorphic.EncryptedVote.fromElectionAndAnswers(self.e,[[1]])
        raw=encrypted.ld_object.serialize()
        cast=models.CastVote.objects.create(voter=voter,vote=encrypted,vote_hash=hash_b64(raw),
            cast_at=datetime.datetime.utcnow(),verified_at=datetime.datetime.utcnow() if verified else None)
        if verified:
            voter.vote=encrypted;voter.vote_hash=cast.vote_hash;voter.cast_at=cast.cast_at;voter.save()
        else:
            models.VoteVerificationJob.objects.create(cast_vote=cast)
        return cast

    def test_zero_vote_election_finishes_without_publication(self):
        self.assertTrue(self.status()['keep_alive'])
        self.assertTrue(process_next_completion())
        self.e.refresh_from_db()
        job=models.ElectionCompletionJob.objects.get(election=self.e)
        self.assertEqual(job.state,'saved')
        self.assertEqual(self.e.result,[[0,0]])
        self.assertIsNone(self.e.result_released_at)
        self.assertIsNotNone(self.e.tallies_combined_at)
        self.assertEqual(job.payload['reader_subjects'],['owner'])
        self.assertFalse(job.payload['ballot']['released'])
        self.assertFalse(self.status()['keep_alive'])
        self.assertFalse(process_next_completion())

    def test_actual_encrypted_vote_is_counted_and_only_aggregate_is_exported(self):
        cast=self.vote()
        self.assertTrue(process_next_completion())
        self.e.refresh_from_db();self.assertEqual(self.e.result,[[0,1]])
        payload=models.ElectionCompletionJob.objects.get(election=self.e).payload
        self.assertEqual(payload['votes'],1)
        self.assertEqual(payload['report']['verified_records'],1)
        self.assertNotIn(cast.vote_hash,json.dumps(payload))
        self.assertNotIn('student@alustudent.com',json.dumps(payload))
        self.assertNotIn('secret_key',json.dumps(payload))
        self.assertNotIn('private_key',json.dumps(payload))
        self.assertEqual(payload['ballot']['result'],[[0,1]])
        self.assertIsNone(self.e.result_released_at)
        for key in self.e.trustee_set.all():self.assertTrue(key.verify_decryption_proofs())

    def test_lost_archive_ack_retries_identical_payload_without_recounting(self):
        self.post.return_value=Mock(status_code=503,json=lambda:{'saved':False})
        self.post.side_effect=None
        process_next_completion()
        job=models.ElectionCompletionJob.objects.get(election=self.e)
        self.assertEqual(job.state,'pending');self.assertIsNone(job.saved_at)
        self.assertIsNotNone(job.payload)
        pending,next_wake,attention=recovery_schedule(datetime.datetime.utcnow())
        self.assertFalse(pending);self.assertIsNotNone(next_wake);self.assertFalse(attention)
        before=job.payload
        job.next_attempt_at=datetime.datetime.utcnow();job.save()
        self.post.return_value=Mock(status_code=200,json=lambda:{'saved':True})
        with patch('helios.election_completion.prepare_payload',side_effect=AssertionError('Must reuse saved payload')):
            process_next_completion()
        job.refresh_from_db();self.assertEqual(job.state,'saved');self.assertEqual(job.payload,before)

    def test_pending_vote_finishes_before_any_final_archive(self):
        self.vote(verified=False)
        process_next_completion()
        job=models.ElectionCompletionJob.objects.get(election=self.e)
        self.assertEqual(job.state,'pending');self.assertIsNone(job.payload)
        self.e.refresh_from_db();self.assertIsNone(self.e.result)
        self.assertTrue(self.status()['pending'])
        self.assertFalse(any(url.endswith('/completed-election') for url,_ in self.sent))

    def test_external_key_is_not_removed_or_replaced(self):
        key=self.e.trustee_set.get();key.secret_key=None;key.save()
        process_next_completion()
        job=models.ElectionCompletionJob.objects.get(election=self.e)
        self.assertEqual(job.state,'blocked');self.assertIsNone(job.saved_at)
        self.assertEqual(self.e.trustee_set.count(),1)
        self.assertIsNone(self.e.trustee_set.get().secret_key)
        self.assertTrue(self.status()['needs_attention']);self.assertFalse(self.status()['keep_alive'])

    def test_policy_review_is_not_bypassed(self):
        with patch('helios.election_completion.require_policy_decisions',side_effect=PermissionDenied('Ballots require an explicit election-policy decision before tallying.')):
            process_next_completion()
        job=models.ElectionCompletionJob.objects.get(election=self.e)
        self.assertEqual(job.state,'blocked');self.assertIsNone(job.payload)
        self.e.refresh_from_db();self.assertIsNone(self.e.result)

    def test_scheduled_window_keeps_warm_and_completion_waits_for_deadline(self):
        now=datetime.datetime.utcnow()
        self.e.voting_ends_at=now+datetime.timedelta(hours=1);self.e.save()
        self.assertFalse(process_next_completion());self.assertTrue(self.status()['keep_alive'])
        self.e.voting_starts_at=now+datetime.timedelta(days=1)
        self.e.voting_ends_at=now+datetime.timedelta(days=2);self.e.save()
        state=self.status();self.assertFalse(state['keep_alive'])
        self.assertEqual(state['next_wake_at'],int((self.e.voting_starts_at-datetime.timedelta(minutes=5)).replace(tzinfo=datetime.timezone.utc).timestamp()*1000))
        self.e.voting_starts_at=now+datetime.timedelta(minutes=4);self.e.save()
        self.assertTrue(self.status()['keep_alive'])

    def test_extension_prevents_early_counting(self):
        self.e.voting_extended_until=datetime.datetime.utcnow()+datetime.timedelta(hours=1);self.e.save()
        self.assertFalse(process_next_completion());self.assertTrue(self.status()['keep_alive'])

    def test_deleted_private_and_unbound_elections_are_never_auto_counted(self):
        self.e.private_p=True;self.e.save();self.assertFalse(process_next_completion())
        self.e.private_p=False;self.e.deleted_at=datetime.datetime.utcnow();self.e.save();self.assertFalse(process_next_completion())
        models.Election.objects_with_deleted.filter(pk=self.e.pk).update(deleted_at=None)
        models.AluElectionBinding.objects.all().delete();self.assertFalse(process_next_completion())

    def test_expired_lease_is_recovered(self):
        job=models.ElectionCompletionJob.objects.create(election=self.e,state='working',
            lease=uuid.uuid4(),lease_until=datetime.datetime.utcnow()-datetime.timedelta(seconds=1))
        process_next_completion();job.refresh_from_db();self.assertEqual(job.state,'saved')

    def test_late_worker_cannot_mark_a_new_lease_saved(self):
        def changed_lease(url,**kwargs):
            models.ElectionCompletionJob.objects.filter(election=self.e).update(lease=uuid.uuid4())
            return Mock(status_code=200,json=lambda:{'saved':True})
        self.post.side_effect=changed_lease
        process_next_completion()
        self.assertEqual(models.ElectionCompletionJob.objects.get(election=self.e).state,'working')

    def test_manual_close_stops_new_voting_before_pending_verification_finishes(self):
        self.e.voting_ends_at=datetime.datetime.utcnow()+datetime.timedelta(hours=1);self.e.save()
        self.vote(verified=False)
        body={'client_id':'alu-helios-demo','election_id':self.e.uuid,'subject':'owner','operation':'close'}
        identity={'subject':'owner','email':'owner@alustudent.com','email_verified':True,'name':'Owner'}
        with patch('helios.alu_management.management_identity',return_value=identity):
            response=Client().post('/helios/alu/manage',json.dumps(body),content_type='application/json',
                HTTP_AUTHORIZATION='Bearer completion-test-secret-with-thirty-two-bytes')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['closed']);self.e.refresh_from_db()
        self.assertTrue(self.e.voting_has_stopped());self.assertIsNone(self.e.result)
        self.assertEqual(models.ElectionCompletionJob.objects.get(election=self.e).state,'pending')

    def test_scheduled_closure_preserves_the_effective_deadline(self):
        expected=self.e.voting_ends_at.replace(tzinfo=datetime.timezone.utc).isoformat()
        process_next_completion();self.e.refresh_from_db()
        self.assertIsNone(self.e.voting_ended_at)
        payload=models.ElectionCompletionJob.objects.get(election=self.e).payload
        self.assertEqual(payload['report']['dates']['voting_ended_at'],expected)
        self.assertEqual(payload['report']['date_sources']['voting_ended_at'],'effective_schedule')

    def test_actual_backend_payload_round_trips_through_neon_receiver(self):
        import os,subprocess
        from pathlib import Path
        from django.db import connection
        app=Path(__file__).resolve().parents[2]/'ALU_Election_App'
        script=app/'scripts/test-completed-election.mjs'
        if not script.exists() or not (app/'node_modules/pg').exists():
            self.skipTest('Sibling frontend integration requires its development dependencies')
        self.vote();process_next_completion()
        payload=models.ElectionCompletionJob.objects.get(election=self.e).payload
        db=connection.settings_dict
        host=db.get('HOST') or '127.0.0.1'
        if host not in ('localhost','127.0.0.1'):
            self.skipTest('Cross-repository archive integration requires local PostgreSQL')
        url=f"postgres://{db['USER']}@{host}:{db.get('PORT') or 5432}/{db['NAME']}"
        result=subprocess.run(['node',str(script),'--from-stdin'],input=json.dumps(payload),
            text=True,capture_output=True,timeout=60,cwd=app,env={**os.environ,'TEST_DATABASE_URL':url})
        self.assertEqual(result.returncode,0,result.stderr[-2500:])
        self.assertIn('completed-election archive, privacy, idempotency and database-only read checks passed',result.stdout)
