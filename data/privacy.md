These days, private data is very important to us, as such I am being transparent about what information [@TheBot]
stores. To jargon bust, internally, discord refers to Servers as "guilds", here i do the same.

For your **guilds**, only the following is stored:
- Your guild_id
- The ID of the channel you've set for questions
- Your set timezone
- Your set time to send questions
- If qotd is enabled
- Whether to pin messages
- What role to mention, if any


Obviously I have to store your **questions** and **suggested questions**, however, I only store the minimum information
needed:

**Suggestions**:
- The suggestion author's ID
- The suggestion guild_ID
- The suggestion's text 
  
Once the suggestion is approved or rejected, it's deleted from [@TheBot]

**Questions**:
- The questions text
- The guild_ID for the question You'll note that the author is not stored, once the question is approved there's no need
  to store it

**Polls**:
- Nothing is stored on [@TheBot]. [@TheBot] uses the message to process the poll

**Users**:
- User ID's of people who have abused [@TheBot] and are now blocked

Upon kicking the bot, **all** data for your guild, members, questions is purged automatically. The downside of this, is
if you have removed the bot and then re-add it, you'll have to start from scratch. The rational here is again, I only
want to store the data [@TheBot] **needs**.

Updated: 24/02/2021

-``LordOfPolls #1010``

If you have any questions, use ``/server`` to join [@TheBot]'s server 