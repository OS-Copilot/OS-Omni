"""Author v2 account/support/logout exercise with owned message evidence."""
from core.evaluation import EvalResult,EvalStatus
from evaluators.cua_review.evaluators.windows.opendriver import OpenDriverWindowsLogoutEvaluator,ID_KEYS
def owned_messages(store,accounts):
 target={str(OpenDriverWindowsLogoutEvaluator.scalar(a,ID_KEYS)) for a in accounts};nodes=OpenDriverWindowsLogoutEvaluator.nodes(store);tickets={str(n.get('id')):n for _,n in nodes if 'userId' in n or 'riderId' in n};found=[]
 for path,n in nodes:
  body=n.get('message') or n.get('body') or n.get('text') or n.get('content')
  initial_ticket=path.startswith('$.supportTickets[') and path.count('.')==1 and 'id' in n and 'userId' in n
  if not isinstance(body,str) or not (initial_ticket or any(k in n for k in ['ticketId','ticket_id','authorId','sender'])):continue
  owner=n.get('authorId') or n.get('userId') or n.get('sender')
  if owner is None:
   ticket=tickets.get(str(n.get('ticketId') or n.get('ticket_id')),{});owner=ticket.get('userId') or ticket.get('riderId')
  if str(owner) in target:found.append(body)
 return found
class RebuiltDriverLogoutEvaluator(OpenDriverWindowsLogoutEvaluator):
 def evaluate(self,context):
  basic=super().evaluate(context)
  if basic.status!=EvalStatus.PASS:return basic
  params=self._context_params(context);store=self.read_store(context['controller'],20);accounts=self.find_account(store,params['expected_account_name'],params['expected_account_email'],'rider');messages=owned_messages(store,accounts);wanted=params['expected_support_messages'];passed=all(messages.count(x)==1 for x in wanted)
  return EvalResult(status=EvalStatus.PASS if passed else EvalStatus.FAIL,message='Author account, owned support messages and logout passed' if passed else 'Required owned support messages absent or duplicated',metadata={**basic.metadata,'version':'author-driver-logout-v2','owned_message_checks':{'expected':wanted,'actual':messages,'passed':passed}})
