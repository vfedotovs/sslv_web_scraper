import smtplib, ssl


port = 465  # For SSL
smtp_server = "smtp.gmail.com"
sender_email = "example@gmail.com"  # Enter your address
receiver_email = "example@gmail.com"  # Enter receiver address
password = input("Please type password and press enter:")

with open ("Mailer_report.txt", "r") as myfile:
        data_list=myfile.readlines()

m =  """\
Subject: **** SSLV Parser Report ****

This message is sent from Python.

"""

for line in data_list:
    m+=line

tmp1 =  m.replace("\xb2", " sq")
message = tmp1.replace("\u20ac", " EUR")

print("Debug info gmailer: printing message content ... ")
print(message)

context = ssl.create_default_context()
with smtplib.SMTP_SSL(smtp_server, port, context=context) as server:
    server.login(sender_email, password)
    server.sendmail(sender_email, receiver_email, message)



