class Invoice:
    def __init__(self, invoice_id, amount, customer_id):
        self.invoice_id = invoice_id
        self.amount = amount
        self.customer_id = customer_id
        self.validate_invoice()

    def validate_invoice(self):
        if self.amount <= 0:
            raise ValueError('Invoice amount must be greater than 0')
        if not isinstance(self.customer_id, str) or not self.customer_id:
            raise ValueError('Invalid customer ID')


class InvoiceService:
    def __init__(self):
        self.invoices = {}  # Simulates storage; replace with database in production

    def create_invoice(self, invoice_id, amount, customer_id):
        invoice = Invoice(invoice_id, amount, customer_id)
        self.invoices[invoice_id] = invoice
        return invoice

    def retrieve_invoice(self, invoice_id):
        return self.invoices.get(invoice_id, None)

    def get_all_invoices(self):
        return list(self.invoices.values())
