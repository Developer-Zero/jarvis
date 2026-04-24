# Strips jsons: "text {...} text" → "{...}"
def formatJson(jsonString):
    string = False
    subs = 0
    firstSub = False
    start = 0
    end = 0
    for char in range(len(jsonString)):
        if subs <= 0:
            if firstSub:
                end = char
                break
            else:
                start = char
        if jsonString[char] == '"':
            string = not string
        elif jsonString[char] == "{" and not string:
            firstSub = True
            subs += 1
        elif jsonString[char] == "}" and not string:
            subs -= 1
    if end > 0:
        return jsonString[start:end]
    else:
        return jsonString[start:]