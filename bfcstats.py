from __future__ import division

from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app, login_required
from google.appengine.ext.webapp import template
from google.appengine.api import users
import gdata.gauth
import gdata.spreadsheets.client
import cgi
import os

#global variables
games = []
spreadsheet_loaded = False
players={}
game_names = []


class Game:
    
    def __init__(self, gamename, players,  started_on_offense, half_at = 8):
        self.scored = []
        self.on_offense=[]
        self.players = {}
        self.started_on_o = started_on_offense
        self.reached_half = False
        self.name = gamename
        self.half_at = half_at
     
        for player in players:
            self.players[player] = []

		
		   
    def add_point(self, players_on,  scored):
        
        #determine if we're on O or on d
        #is this the first point?
        if len(self.scored) == 0:
            self.on_offense.append(self.started_on_o)
        #is this the first point after half?
        elif(((sum(self.scored) == self.half_at ) or ((len(self.scored) -sum(self.scored)) == self.half_at)) and not self.reached_half):
            self.reached_half = True
            if self.started_on_o:
				self.on_offense.append(False)
            else:
                self.on_offense.append(True)
        #look at if we scored last point
        else: 
			if self.scored[-1]:
				self.on_offense.append(False)
			else:
				self.on_offense.append(True)
        
        #did we score?        
        self.scored.append(scored)
               
        #update player tallys
        for player,  tally in self.players.iteritems():
            if player in players_on:
                tally.append(True)
            else:
                tally.append(False)
                
		
	#for testing only...
    def print_game(self):
        print  "Players: \n"
        for player,  tally in  self.players.iteritems():
           print  player
           print tally
        print  "Scores: "
        print self.scored
        print "On Offense"
        print self.on_offense

# Constants included for ease of understanding. It is a more common
# and reliable practice to create a helper for reading a Consumer Key
# and Secret from a config file. You may have different consumer keys
# and secrets for different environments, and you also may not want to
# check these values into your source code repository.
SETTINGS = {
    'APP_NAME': 'bytownstats-calculator',
    'CONSUMER_KEY': 'bytownstats.appspot.com',
    'CONSUMER_SECRET': 'QDJ8gxbyMaefmTAa3LyRgz15',
    'SCOPES': ['https://spreadsheets.google.com/feeds/']
    }


# Create an instance of the DocsService to make API calls
gdocs = gdata.spreadsheets.client.SpreadsheetsClient(source = SETTINGS['APP_NAME'])


class Fetcher(webapp.RequestHandler):

    @login_required
    def get(self):
        """This handler is responsible for fetching an initial OAuth
        request token and redirecting the user to the approval page."""

        current_user = users.get_current_user()
        scopes = SETTINGS['SCOPES']
        oauth_callback = 'http://%s/step2' % self.request.host
        consumer_key = SETTINGS['CONSUMER_KEY']
        consumer_secret = SETTINGS['CONSUMER_SECRET']
        request_token = gdocs.get_oauth_token(scopes, oauth_callback,
                                              consumer_key, consumer_secret)

        # Persist this token in the datastore.
        request_token_key = 'request_token_%s' % current_user.user_id()
        gdata.gauth.ae_save(request_token, request_token_key)

        # Generate the authorization URL.
        approval_page_url = request_token.generate_authorization_url()
        url_text = "Click here to authenticate!"
        selector = '<select size=1> <option> Not Authenticated Yet </option></select>'
        template_values = {'authlink': approval_page_url,  'authtext':url_text,'selector':selector }
        path = os.path.join(os.path.dirname(__file__), 'index.html')
        self.response.out.write(template.render(path, template_values))


    
class MainPage(webapp.RequestHandler):

    @login_required
    def get(self):
        """When the user grants access, they are redirected back to this
        handler where their authorized request token is exchanged for a
        long-lived access token."""

        current_user = users.get_current_user()
        request_token_key = 'request_token_%s' % current_user.user_id()
        request_token = gdata.gauth.ae_load(request_token_key)
        gdata.gauth.authorize_request_token(request_token, self.request.uri)
        gdocs.auth_token = gdocs.get_access_token(request_token)
        access_token_key = 'access_token_%s' % current_user.user_id()
        gdata.gauth.ae_save(request_token, access_token_key)
        feed = gdocs.GetSpreadsheets()
        self.select_spreadsheet(feed)

    
    def select_spreadsheet(self,  feed):
        global spreadsheet_loaded
        global games
        global players
        global game_names
        global team_effs
        global team_effs_baseline
        games = []
        players={}
        player_effs = {}
        team_effs = (0, 0, 0, 0)
        team_effs_baseline = (0, 0, 0, 0)
        player_effs_baseline={}
        spreadsheet_loaded=False
        selector = '''
        <form action="/results" method="POST">
        <select name="sheet">'''
        for entry in feed.entry:
            selector += '<option value='+entry.id.text.rsplit('/', 1)[1]+'>'+entry.title.text+'</option>'
        selector += '</select><INPUT TYPE=SUBMIT VALUE="Select"></form> </br> Note: It can take some time to load your spreadsheet... please be patient!'
        template_values = {'authlink': 'NULL','authtext':'Successfully Authenticated!',   'selector':selector }
        path = os.path.join(os.path.dirname(__file__), 'index.html')
        self.response.out.write(template.render(path, template_values))
        

class GamePage(webapp.RequestHandler):
   
    def post(self):
        global spreadsheet_loaded
        global games
        global players
        global game_names
        global team_effs
        global team_effs_baseline
        if not spreadsheet_loaded:
            game_names = []
            spreadsheet_key = cgi.escape(self.request.get('sheet'))
            worksheets = gdocs.GetWorksheets(spreadsheet_key)
            for sheet in worksheets.entry:
                game,  players = self.create_game(spreadsheet_key, sheet.id.text.rsplit('/', 1)[1] ,  sheet.title.text, players)
                games.append(game)
                game_names.append(sheet.title.text)
            spreadsheet_loaded = True
               
        player_effs = []
        
        returnedgames = self.request.get_all('games')
        players_on = self.request.get_all('players_on')
        players_off = self.request.get_all('players_off')

		#selecting no games is the same as selecting all:
        if not returnedgames:
            returnedgames = game_names
        
        #calculate the efficiency for each player:
        for player in players.iterkeys():
            player_effs.append(self.calculate_player_efficiency(player, returnedgames, players_on, players_off))
                
        #calculate team efficiency:
        team_efficiency = self.calculate_team_efficiency(returnedgames, players_on, players_off)
        
        player_names = []
        for someguy in sorted(players.keys()):
            selecton = ""
            selectoff = ""
            if someguy in players_on:
                selecton = " selected "
            if someguy in players_off:
                selectoff = " selected "
            player_names.append( (someguy,selecton,selectoff) )
        games_to_use = []
        game_diagrams = []
        for somegame in sorted(game_names):
            selected = ""
            if somegame in returnedgames:
                selected = " selected "
                game_diagrams.append( self.produce_game_html(somegame, players_on, players_off) )
            games_to_use.append( (somegame, selected) )
			
        
			
        
        
        #get combos of two players
        two_players = self.find_top_two_players(returnedgames, players_on, players_off)
        
        #get combos of three players
        three_players = self.find_top_three_players(returnedgames, players_on, players_off)
        
        template_values = {'games_to_use': games_to_use,
							'game_diagrams': game_diagrams,
							'team_effs': team_efficiency,
                            'players_to_use': player_names,
                            'player_effs': player_effs,
                            'two_players_o': two_players[0],
                            'two_players_d': two_players[1],
                            'three_players_o': three_players[0],
                            'three_players_d': three_players[1]
                            }
        path = os.path.join(os.path.dirname(__file__), 'results.html')
        self.response.out.write(template.render(path, template_values))
	
    def get_game_by_name(self, gamename):
		global games
		for game in games:
			if game.name == gamename:
				return game
		return None
    
    
    def produce_game_html(self,gamename,players_on=None,players_off=None):
	
	we_scored_graph = ""
	they_scored_graph = ""
	midline_graph = ""
	we_scored = 0
	they_scored=0
	
	game = self.get_game_by_name(gamename)
	
	for i in range(0, len(game.scored)):  
	
	    title = "  players: "
	    for player in players.keys():
		try:
		    if game.players[player][i]:
			title += player+' '
		except KeyError:
		    continue
	    
	    our_color = '#FFFFFF'
	    their_color = '#FFFFFF'
		
	    if game.scored[i]:
		we_scored += 1
		if game.on_offense[i]:
		    our_color = '#0000FF'
		else:
		    our_color = '#00FF00'
	    else:
		they_scored += 1
		if game.on_offense[i]:
		    their_color = '#FF0000'
		else:
		    their_color = '#0000FF'

	    #check the constraints, and adjust as necessary.
	    try:
		if players_on:
		    for constraint in players_on:
			if not game.players[constraint][i]:
			    raise KeyError('please continue!')
	    except KeyError:
		our_color = '#FFFFFF'
		their_color = '#FFFFFF'
		pass
	    try:
		#check players_off constraint:
		if players_off:
		    for constraint in players_off:
			if game.players[constraint][i]:
			    raise AssertionError
	    #if a "players_off" player isn't even playing that game, that's okay, just proceed
	    except KeyError:
		pass
	    #if the player WAS on the field, we don't record the scores for this point.
	    except AssertionError:
		our_color = '#FFFFFF'
		their_color = '#FFFFFF'
		pass
		
	    title = ' title = "'+str(we_scored) + ' - ' + str(they_scored) + title + '"'
		
	    we_scored_graph += '<td width=10px height=25px bgcolor='+our_color+title+'></td>'
	    they_scored_graph += '<td width=10px height=25px bgcolor='+their_color+title+'></td>'
	    midline_graph += '<td width=10px height=2px bgcolor="#000000"></td>' 
	    
	
	output = '<table border=0 cellspacing=0><tr><td> Us </td><td></td>'
	output += we_scored_graph+'</tr>'
	output += '<tr height=2px ><td height=2px color="#000000"></td><td height=2px color="#000000"></td>'+midline_graph+'</tr>'
	output += '<tr><td> Them </td><td></td>' + they_scored_graph 
	output += '</tr></table>'
	
	return (game.name, output)
	    
    def create_game(self, spreadsheet_key,  worksheet_id,  name, players):
        #print '<div>'+name+'</div>'
        list_feed = 'https://spreadsheets.google.com/feeds/list/%s/%s/private/full' % (spreadsheet_key, worksheet_id)
        feed = gdocs.get_feed(list_feed, desired_class=gdata.spreadsheets.data.ListsFeed)
        scored = ""
        started_on_o = False
        this_games_players={}
        half_at = 8
        for row in feed.entry:
            if row.title.text.strip() == "Scored":
                scored = row.content.text 
                continue
            elif row.title.text == "started_on_o":
                started_on_o = True
                continue
            elif row.title.text == "half_at":
				half_at = int(row.content.text.split(':')[1].strip())
				continue
            players[row.title.text] = row.content.text
            this_games_players[row.title.text] = row.content.text
        
       
        newgame = Game(name,  this_games_players.keys(), started_on_o, half_at)
        for point in scored.split(','):
            #print '<div>'+point+'</div>'
            players_on = []
            bits = point.split(':')
            for player in this_games_players.keys():
                #print '<div>'+player+'</div>'
                if bits[0].strip() in players[player]:
                    players_on.append(player)
            newgame.add_point(players_on,  int(bits[1].strip()))
        
        return newgame,  players
    
    def calculate_team_efficiency(self, games_to_use=None,  players_on=None, players_off=None):
        opoints=0
        dpoints=0
        oscored=0
        dscored=0
        global games
        
        # iterate over the games
        for game in games:
            if games_to_use:
                if not game.name in games_to_use:
                    continue
                    
                    
            for i in range(0, len(game.scored)):  
                try:
                    if players_on:
                        for constraint in players_on:
                            if not game.players[constraint][i]:
                                raise KeyError('please continue!')
                except KeyError:
                    continue
                try:
                    #check players_off constraint:
                    if players_off:
                        for constraint in players_off:
                            if game.players[constraint][i]:
                                raise AssertionError
                #if a "players_off" player isn't even playing that game, that's okay, just proceed
                except KeyError:
                    pass
                #if the player WAS on the field, we don't record the scores for this point.
                except AssertionError:
                    continue
                
                #if we reach this point, we're good!
                if game.on_offense[i]:
                    opoints += 1
                    if game.scored[i]:
                        oscored += 1
                else:
                    dpoints += 1
                    if game.scored[i]:
                        dscored += 1
        oeff = 0
        if opoints:
            oeff = oscored/opoints
        deff = 0
        if dpoints:
            deff = dscored/dpoints
        
        return ("TEAM", opoints,  oscored,  "%.2f" % oeff, dpoints,  dscored, "%.2f" % deff) 
    
    def calculate_player_efficiency(self, player_name,  games_to_use=None,  players_on=None, players_off=None):
        opoints=0
        dpoints=0
        oscored=0
        dscored=0
        global games
        
        # iterate over the games
        for game in games:
            if games_to_use:
                if not game.name in games_to_use:
                    continue
            
            #iterate over the points in each game
            for i in range(0, len(game.scored)):
                            
                
                #print '<div>'+ player_name + " "+str(opoints) + ' ' + str(oscored) + ' '+str(dpoints)+' '+str(dscored)+'</div>'
                #print '<div>'+ str(game.on_offense[i])+' '+str(game.scored[i])+'</div>'
                #print '<div>'+game.name+'</div>'
                #for someplayers in game.players.iterkeys():
                 #   print '<div>'+someplayers+' '
                  #  for point in game.players[someplayers]:
                   #     print str(point)+' '
                   # print '</div>'
                #players may not be defined in each game:
                try:
                    #check if the player was on the field:
                    if not game.players[player_name][i]:
                        continue
                        
                    #check players_on constraint:
                    if players_on:
                        for constraint in players_on:
                            if not game.players[constraint][i]:
                                raise KeyError('not here...')
                except KeyError:
                    continue
                    
                try:
                    #check players_off constraint:
                    if players_off:
                        for constraint in players_off:
                            if game.players[constraint][i]:
                                raise AssertionError
                #if a "players_off" player isn't even playing that game, that's okay, just proceed
                except KeyError:
                    pass
                except AssertionError:
                    continue
                    
                #if we reach this point in the loop, the player is on, and all constraints
                #have been satisfied.  Record the results
                if game.on_offense[i]:
                    opoints += 1
                    if game.scored[i]:
                        oscored += 1
                else:
                    dpoints += 1
                    if game.scored[i]:
                        dscored += 1
                #print '<div>'+ player_name + " "+str(i) +'</div>'
        
        oeff = 0
        if opoints:
            oeff = oscored/opoints
        deff = 0
        if dpoints:
            deff = dscored/dpoints
        
        return (player_name, opoints,  oscored,  "%.2f" % oeff, dpoints,  dscored, "%.2f" % deff)
        
    
    def find_top_two_players(self, games=None, players_on=None,  players_off=None):
        all_combos_o = []
        all_combos_d = []
        
        if not players_on:
            players_on = []
        
        playerlist = players.keys()
        for i in range(0, len(playerlist)):
            for j in range(i+1, len(playerlist)):
                
                player1 = playerlist[i]
                player2 = playerlist[j]
                
                players_to_use = []
                players_to_use.extend(players_on)
                players_to_use.append(player1)
                players_to_use.append(player2)
                result = self.calculate_team_efficiency(games, players_to_use, players_off)
                if (result[1] > 5):                                    
                    all_combos_o.append((player1+'<br>'+player2,result[1],result[2],result[3]))                   
                                    
                if (result[4] > 5):                                    
                    all_combos_d.append((player1+'<br>'+player2,result[4],result[5],result[6]))
                    
        return (all_combos_o, all_combos_d)
        
    
    def find_top_three_players(self, games=None, players_on=None,  players_off=None):
        all_combos_o = []
        all_combos_d = []
        
        if not players_on:
            players_on = []
        
        playerlist = players.keys()
        for i in range(0, len(playerlist)):
            for j in range(i+1, len(playerlist)):
                for k in range(j+1, len(playerlist)):
                
                    player1 = playerlist[i]
                    player2 = playerlist[j]
                    player3=playerlist[k]
                
                    players_to_use = []
                    players_to_use.extend(players_on)
                    players_to_use.append(player1)
                    players_to_use.append(player2)
                    players_to_use.append(player3)
                    result = self.calculate_team_efficiency(games, players_to_use, players_off)
                    if (result[1] > 5):                                    
                        all_combos_o.append((player1+'<br>'+player2+'<br>'+player3,result[1],result[2],result[3]))                   
                                    
                    if (result[4] > 5):                                    
                        all_combos_d.append((player1+'<br>'+player2+'<br>'+player3,result[4],result[5],result[6]))
                    
        return (all_combos_o, all_combos_d)

        
def main():
    application = webapp.WSGIApplication([('/', Fetcher),
                                          ('/step2', MainPage),
                                          ('/results', GamePage)],
                                         debug=True)
    run_wsgi_app(application)


if __name__ == "__main__":
    main()

