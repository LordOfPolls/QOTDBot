These days, private data is very important to us, as such I am being transparent about what information [@TheBot] stores. To jargon bust, internally, discord refers to Servers as "guilds", here I do the same.

For your **guilds**, only the following is stored:
- Your guild_id
- The ID of the channel you've set for questions
- Your set timezone
- Your set time to send questions
- If qotd is enabled
- Whether to pin messages
- What role to mention, if any


Obviously I have to store your **questions** and **suggested questions**, however, I only store the minimum information needed:

**Suggestions**:
- The suggestion author's ID
- The suggestion guild_ID
- The suggestion's text 
  
Once the suggestion is approved or rejected, it's deleted from [@TheBot]

**Questions**:
- The questions text
- The guild_ID for the question You'll note that the author is not stored, once the question is approved there's no need to store it

**Polls**:

Polls need a decent amount of information to operate, but all of it is operational data
- The title of the poll
- The options of the poll
- The author id of the poll
- The channel id the poll is in
- The guild id the poll is in
- When should the poll be closed automatically (if at all)
- Are single votes enforced?

**Users**:
- User ID's of people who have abused [@TheBot] and are now blocked

Upon kicking the bot, **all** data for your guild, members, questions is purged automatically. The downside of this, is if you have removed the bot and then re-add it, you'll have to start from scratch. The rational here is again, I only want to store the data [@TheBot] **needs**.

Updated: 04/03/2021

-``LordOfPolls #1010``

If you have any questions, use ``/server`` to join [@TheBot]'s server 