from flask import Flask, render_template, request

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/sobre")
def sobre():
    return render_template("sobre.html")


@app.route("/projetos")
def projetos():
    projetos = [
        {
            "titulo": "Sistema de Gestão Médica",
            "descricao": "Plataforma completa para clínicas e consultórios gerenciarem pacientes, agendamentos e prontuários.",
            "icone": "🏥",
        },
        {
            "titulo": "Portal de Telemedicina",
            "descricao": "Sistema de consultas online com videochamadas integradas e prescrição digital.",
            "icone": "💻",
        },
        {
            "titulo": "App de Saúde & Bem-estar",
            "descricao": "Aplicativo mobile para monitoramento de saúde, lembretes de medicamentos e acompanhamento médico.",
            "icone": "📱",
        },
        {
            "titulo": "Dashboard Analytics Médico",
            "descricao": "Painel de indicadores para hospitais e clínicas com relatórios em tempo real.",
            "icone": "📊",
        },
        {
            "titulo": "Integração Laboratorial",
            "descricao": "Sistema de integração entre laboratórios e clínicas para envio e consulta de resultados.",
            "icone": "🔬",
        },
        {
            "titulo": "Chatbot de Triagem",
            "descricao": "Assistente virtual inteligente para triagem inicial de pacientes via WhatsApp e web.",
            "icone": "🤖",
        },
    ]
    return render_template("projetos.html", projetos=projetos)


@app.route("/contato", methods=["GET", "POST"])
def contato():
    if request.method == "POST":
        nome = request.form.get("nome")
        email = request.form.get("email")
        mensagem = request.form.get("mensagem")
        return render_template("contato.html", enviado=True, nome=nome)
    return render_template("contato.html", enviado=False)


app.run(host="0.0.0.0", port=80)

