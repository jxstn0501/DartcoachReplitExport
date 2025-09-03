from flask_cors import CORS
from flask import Flask, request, jsonify, flash, redirect, url_for
import requests
import os
import json
from datetime import datetime
from werkzeug.utils import secure_filename
from ui import ui_bp   # Import Blueprint

app = Flask(__name__)
CORS(app)
app.secret_key = 'your-secret-key-here'

# API Configuration
PARSEEXTRACT_API_URL = "https://api.parseextract.com/v1/data-extract"
PARSEEXTRACT_API_KEY = os.getenv("PARSEEXTRACT_API_KEY", "TjHTQf68b6017f2a1e42312f494130ecOXsT")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
SHEETSDB_URL = os.getenv("SHEETSDB_URL")

# Upload Configuration
UPLOAD_FOLDER = '/tmp/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'docx', 'doc'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/api/upload-statistics", methods=["POST"])
def upload_statistics():
    """Upload and process dart statistics files via ParseExtract API"""
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei hochgeladen"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Keine Datei ausgewählt"}), 400
    
    if not allowed_file(file.filename):
        return jsonify({"error": "Dateityp nicht erlaubt"}), 400
    
    try:
        # Save uploaded file temporarily
        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        
        # Process with ParseExtract API
        headers = {"Authorization": f"Bearer {PARSEEXTRACT_API_KEY}"}
        
        with open(filepath, 'rb') as f:
            files = {"file": (filename, f, file.mimetype)}
            data = {"prompt": "Extract dart game statistics including player names, scores, rounds, throws, checkout percentages, and PPR (Points Per Round) from this document. Format as structured data."}
            
            response = requests.post(PARSEEXTRACT_API_URL, files=files, data=data, headers=headers, timeout=(10,120))
        
        # Clean up temporary file
        os.remove(filepath)
        
        if response.status_code == 200:
            extracted_data = response.json()
            return jsonify({
                "success": True,
                "data": extracted_data,
                "message": "Statistiken erfolgreich extrahiert"
            })
        else:
            return jsonify({
                "error": f"ParseExtract API Fehler: {response.status_code}"
            }), 500
            
    except Exception as e:
        # Clean up temporary file on error
        if 'filepath' in locals() and os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({"error": f"Verarbeitungsfehler: {str(e)}"}), 500

@app.route("/api/save-to-sheets", methods=["POST"])
def save_to_sheets():
    """Save extracted data to Google Sheets via sheetsdb.io"""
    if not SHEETSDB_URL:
        return jsonify({"error": "Google Sheets URL nicht konfiguriert"}), 500
    
    try:
        raw_data = request.json
        if not raw_data:
            return jsonify({"error": "Keine Daten zum Speichern"}), 400
        
        # Transform data to SheetDB.io format
        # The API expects data in this format: {"data": [{"column1": "value1", ...}]}
        sheet_data = transform_to_sheet_format(raw_data)
        
        # Send to sheetsdb.io with proper headers
        headers = {
            'Content-Type': 'application/json'
        }
        
        response = requests.post(
            SHEETSDB_URL, 
            json=sheet_data, 
            headers=headers,
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            result = response.json()
            return jsonify({
                "success": True,
                "message": f"Daten erfolgreich in Google Sheets gespeichert ({result.get('created', '?')} Zeilen erstellt)"
            })
        else:
            error_text = response.text
            return jsonify({
                "error": f"Google Sheets Fehler: {response.status_code} - {error_text}"
            }), 500
            
    except Exception as e:
        return jsonify({"error": f"Fehler beim Speichern: {str(e)}"}), 500

def transform_to_sheet_format(extracted_data):
    """Transform ParseExtract response to Google Sheets format with specific columns:
    game_id, mode, legType, date, duration, player, round, throw1, throw2, throw3, score, rest, bust
    """
    rows = []
    current_timestamp = datetime.now()
    game_id = f"game_{int(current_timestamp.timestamp())}"
    
    # Parse extracted data and create rows matching your Google Sheets structure
    try:
        # Try to extract dart game information from the AI response
        dart_data = parse_dart_data(extracted_data)
        
        for entry in dart_data:
            row = {
                'game_id': entry.get('game_id', game_id),
                'mode': entry.get('mode', '501'),  # Default to 501 game
                'legType': entry.get('legType', 'standard'),
                'date': entry.get('date', current_timestamp.strftime('%Y-%m-%d')),
                'duration': entry.get('duration', ''),
                'player': entry.get('player', 'Unknown'),
                'round': entry.get('round', '1'),
                'throw1': entry.get('throw1', ''),
                'throw2': entry.get('throw2', ''),
                'throw3': entry.get('throw3', ''),
                'score': entry.get('score', '0'),
                'rest': entry.get('rest', '501'),
                'bust': entry.get('bust', 'false')
            }
            rows.append(row)
    
    except Exception as e:
        # Fallback: Create a single row with available data
        print(f"Error parsing dart data: {e}")
        
        # Try to extract any player names or scores from the text
        player_name = extract_player_name(extracted_data)
        
        fallback_row = {
            'game_id': game_id,
            'mode': '501',
            'legType': 'imported',
            'date': current_timestamp.strftime('%Y-%m-%d'),
            'duration': '',
            'player': player_name,
            'round': '1',
            'throw1': '',
            'throw2': '',
            'throw3': '',
            'score': '0',
            'rest': '501',
            'bust': 'false'
        }
        rows.append(fallback_row)
    
    return {"data": rows}

def parse_dart_data(extracted_data):
    """Parse extracted data to find dart game information"""
    entries = []
    
    # Convert to string if it's not already
    if not isinstance(extracted_data, str):
        data_str = json.dumps(extracted_data) if isinstance(extracted_data, (dict, list)) else str(extracted_data)
    else:
        data_str = extracted_data
    
    # Look for common dart patterns in the extracted text
    import re
    
    # Try to find player names (common patterns: PLAYER123, Name123, etc.)
    player_matches = re.findall(r'([A-Z][A-Z0-9]+|\w+\d+)', data_str)
    
    # Try to find scores and throws (T20, D16, 180, etc.)
    throw_matches = re.findall(r'(T\d+|D\d+|S\d+|\b\d{1,3}\b)', data_str)
    
    # Try to find round information
    round_matches = re.findall(r'(?:round|runde|leg)\s*(\d+)', data_str.lower())
    
    # Create entries based on found data
    if player_matches:
        for i, player in enumerate(player_matches[:5]):  # Max 5 players
            entry = {
                'player': player,
                'round': str(i + 1),
                'game_id': f"imported_{int(datetime.now().timestamp())}_{i}"
            }
            
            # Try to assign throws if available
            start_idx = i * 3
            if len(throw_matches) > start_idx:
                entry['throw1'] = throw_matches[start_idx] if start_idx < len(throw_matches) else ''
                entry['throw2'] = throw_matches[start_idx + 1] if start_idx + 1 < len(throw_matches) else ''
                entry['throw3'] = throw_matches[start_idx + 2] if start_idx + 2 < len(throw_matches) else ''
                
                # Calculate score from throws
                score = calculate_throw_score(entry.get('throw1', ''), entry.get('throw2', ''), entry.get('throw3', ''))
                entry['score'] = str(score)
                entry['rest'] = str(501 - score)  # Assuming 501 game
            
            entries.append(entry)
    
    # If no structured data found, create at least one entry
    if not entries:
        entries.append({
            'player': 'Imported_Player',
            'round': '1',
            'game_id': f"imported_{int(datetime.now().timestamp())}"
        })
    
    return entries

def extract_player_name(data):
    """Extract player name from data"""
    if isinstance(data, dict):
        # Look for common player name fields
        for key in ['player', 'name', 'spieler', 'user']:
            if key in data:
                return str(data[key])
    
    # Try to extract from string
    data_str = str(data)
    import re
    
    # Look for player name patterns
    player_match = re.search(r'([A-Z][A-Z0-9]+|\w+\d+)', data_str)
    if player_match:
        return player_match.group(1)
    
    return 'Unknown_Player'

def calculate_throw_score(throw1, throw2, throw3):
    """Calculate total score from three throws"""
    total = 0
    
    for throw in [throw1, throw2, throw3]:
        if not throw:
            continue
            
        try:
            if throw.startswith('T'):  # Triple
                total += int(throw[1:]) * 3
            elif throw.startswith('D'):  # Double  
                total += int(throw[1:]) * 2
            elif throw.startswith('S'):  # Single
                total += int(throw[1:])
            elif throw.isdigit():  # Direct number
                total += int(throw)
        except (ValueError, IndexError):
            continue
    
    return total

def flatten_player_data(player_data):
    """Flatten player data for spreadsheet columns"""
    flattened = {}
    
    for key, value in player_data.items():
        if isinstance(value, (dict, list)):
            flattened[key] = json.dumps(value)  # Store complex data as JSON string
        else:
            flattened[key] = str(value)
    
    return flattened

def flatten_data(data_item):
    """Flatten general data for spreadsheet columns"""
    flattened = {}
    
    for key, value in data_item.items():
        if isinstance(value, (dict, list)):
            flattened[key] = json.dumps(value)  # Store complex data as JSON string
        else:
            flattened[key] = str(value)
    
    return flattened

@app.route("/api/get-players", methods=["GET"])
def get_players():
    """Get list of players from Google Sheets"""
    if not SHEETSDB_URL:
        return jsonify({"error": "Google Sheets URL nicht konfiguriert"}), 500
    
    try:
        # Fetch data from sheets to extract player names
        response = requests.get(f"{SHEETSDB_URL}?select=player", timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            # Extract unique player names
            players = list(set([row.get('player', '') for row in data if row.get('player')]))
            players.sort()
            
            return jsonify({
                "success": True,
                "players": players
            })
        else:
            return jsonify({
                "error": f"Google Sheets Fehler: {response.status_code}"
            }), 500
            
    except Exception as e:
        return jsonify({"error": f"Fehler beim Abrufen der Spieler: {str(e)}"}), 500

@app.route("/api/player-stats/<player_name>", methods=["GET"])
def get_player_stats(player_name):
    """Get statistics for a specific player"""
    if not SHEETSDB_URL:
        return jsonify({"error": "Google Sheets URL nicht konfiguriert"}), 500
    
    try:
        # Fetch player data from sheets
        response = requests.get(f"{SHEETSDB_URL}?player={player_name}", timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            # Calculate KPIs
            stats = calculate_player_stats(data, player_name)
            
            return jsonify({
                "success": True,
                "stats": stats
            })
        else:
            return jsonify({
                "error": f"Google Sheets Fehler: {response.status_code}"
            }), 500
            
    except Exception as e:
        return jsonify({"error": f"Fehler beim Abrufen der Statistiken: {str(e)}"}), 500

def calculate_player_stats(data, player_name):
    """Calculate player statistics from game data"""
    player_games = [game for game in data if game.get('player') == player_name]
    
    if not player_games:
        return {
            "ppr": 0,
            "checkout_percentage": 0,
            "checkout_points": [],
            "win_rate": 0,
            "visits_buckets": {"60+": 0, "100+": 0, "140+": 0, "180": 0},
            "total_games": 0
        }
    
    total_points = sum(game.get('points', 0) for game in player_games)
    total_rounds = sum(game.get('rounds', 1) for game in player_games)
    ppr = round(total_points / total_rounds, 2) if total_rounds > 0 else 0
    
    successful_checkouts = len([game for game in player_games if game.get('checkout', False)])
    checkout_percentage = round((successful_checkouts / len(player_games)) * 100, 2) if player_games else 0
    
    checkout_points = [game.get('checkout_points', 0) for game in player_games if game.get('checkout_points')]
    
    wins = len([game for game in player_games if game.get('win', False)])
    win_rate = round((wins / len(player_games)) * 100, 2) if player_games else 0
    
    # Calculate visits buckets
    visits_buckets = {"60+": 0, "100+": 0, "140+": 0, "180": 0}
    for game in player_games:
        points = game.get('points', 0)
        if points >= 180:
            visits_buckets["180"] += 1
        elif points >= 140:
            visits_buckets["140+"] += 1
        elif points >= 100:
            visits_buckets["100+"] += 1
        elif points >= 60:
            visits_buckets["60+"] += 1
    
    return {
        "ppr": ppr,
        "checkout_percentage": checkout_percentage,
        "checkout_points": checkout_points,
        "win_rate": win_rate,
        "visits_buckets": visits_buckets,
        "total_games": len(player_games)
    }

@app.route("/")
def home():
    return "Backend läuft! Sende POST an /extract"
    
    
@app.route("/api/generate-training-plan", methods=["POST"])
def generate_training_plan():
    """Generate AI-powered training plan using GPT-4o-mini"""
    if not OPENAI_API_KEY:
        return jsonify({"error": "OpenAI API Key nicht konfiguriert"}), 500
    
    try:
        data = request.json
        player_name = data.get('player_name')
        
        if not player_name:
            return jsonify({"error": "Spielername erforderlich"}), 400
        
        # Get last 5 legs from Google Sheets
        recent_games = get_recent_player_games(player_name, limit=5)
        
        if not recent_games:
            return jsonify({"error": "Keine aktuellen Spieldaten gefunden"}), 404
        
        # Generate training plan with OpenAI
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        prompt = f"""
        Analysiere die folgenden Dart-Spieldaten von {player_name} und erstelle einen personalisierten Trainingsplan:
        
        Spieldaten: {json.dumps(recent_games, indent=2)}
        
        Bitte erstelle eine strukturierte Antwort mit folgenden Abschnitten:
        1. Analyse der Spielstärken
        2. Identifizierte Schwächen
        3. Spezifische Übungen (als Tabelle mit Übung, Dauer, Fokus)
        4. Motivierende Schlussnote
        
        Formatiere die Antwort als JSON mit den Schlüsseln: analysis, strengths, weaknesses, exercises (Array mit name, duration, focus), motivation
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Du bist ein professioneller Dart-Trainer. Erstelle präzise, praktische Trainingspläne basierend auf Spielerdaten."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        # Parse GPT response
        ai_response = response.choices[0].message.content
        
        # Try to parse as JSON, fallback to text
        try:
            training_plan = json.loads(ai_response)
        except:
            training_plan = {
                "analysis": ai_response,
                "strengths": [],
                "weaknesses": [],
                "exercises": [],
                "motivation": "Weiter so! Regelmäßiges Training führt zur Verbesserung."
            }
        
        # Add metadata
        training_plan.update({
            "player_name": player_name,
            "created_at": datetime.now().isoformat(),
            "games_analyzed": len(recent_games)
        })
        
        return jsonify({
            "success": True,
            "training_plan": training_plan
        })
        
    except Exception as e:
        return jsonify({"error": f"Fehler bei der Trainingsplan-Generierung: {str(e)}"}), 500

@app.route("/api/save-to-notion", methods=["POST"])
def save_to_notion():
    """Save training plan to Notion"""
    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        return jsonify({"error": "Notion API nicht konfiguriert"}), 500
    
    try:
        data = request.json
        training_plan = data.get('training_plan')
        
        if not training_plan:
            return jsonify({"error": "Trainingsplan erforderlich"}), 400
        
        # Prepare Notion page data
        notion_data = {
            "parent": {"database_id": NOTION_DATABASE_ID},
            "properties": {
                "Titel": {
                    "title": [
                        {
                            "text": {
                                "content": f"Trainingsplan - {training_plan.get('player_name', 'Unbekannt')}"
                            }
                        }
                    ]
                },
                "Spieler": {
                    "rich_text": [
                        {
                            "text": {
                                "content": training_plan.get('player_name', 'Unbekannt')
                            }
                        }
                    ]
                },
                "Datum": {
                    "date": {
                        "start": training_plan.get('created_at', datetime.now().isoformat())
                    }
                }
            },
            "children": [
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"type": "text", "text": {"content": "Analyse"}}]
                    }
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": str(training_plan.get('analysis', ''))}}]
                    }
                }
            ]
        }
        
        # Add exercises as table if available
        if training_plan.get('exercises'):
            exercises_text = "\\n".join([
                f"• {ex.get('name', '')}: {ex.get('duration', '')} - {ex.get('focus', '')}"
                for ex in training_plan['exercises']
            ])
            
            notion_data["children"].extend([
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"type": "text", "text": {"content": "Übungen"}}]
                    }
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": exercises_text}}]
                    }
                }
            ])
        
        # Send to Notion API
        headers = {
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        
        response = requests.post(
            "https://api.notion.com/v1/pages",
            headers=headers,
            json=notion_data,
            timeout=30
        )
        
        if response.status_code == 200:
            return jsonify({
                "success": True,
                "message": "Trainingsplan erfolgreich in Notion gespeichert",
                "notion_url": response.json().get('url')
            })
        else:
            return jsonify({
                "error": f"Notion API Fehler: {response.status_code} - {response.text}"
            }), 500
            
    except Exception as e:
        return jsonify({"error": f"Fehler beim Speichern in Notion: {str(e)}"}), 500

def get_recent_player_games(player_name, limit=5):
    """Get recent games for a player from Google Sheets"""
    if not SHEETSDB_URL:
        return []
    
    try:
        response = requests.get(
            f"{SHEETSDB_URL}?player={player_name}&limit={limit}&order=created_at.desc",
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json()
        
    except Exception as e:
        print(f"Error fetching recent games: {e}")
    
    return []

app.register_blueprint(ui_bp, url_prefix="/ui")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
